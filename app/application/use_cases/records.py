"""Records du serveur (salon des records, `/records`, 07/11/2026).

  • `track_fight` : après chaque combat de zone, les exploits de chacun (hors
    événement lunaire). Ne fait JAMAIS échouer les récompenses du combat.
  • `run_night` : une fois par nuit (jour de Paris) — détenteurs de chaque
    record, ce qui a changé depuis la veille, titres tournants. Idempotent.
  • `personal` : où en est un joueur face à chaque record.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.application.services.exclusive_title_service import ExclusiveTitleService
from app.domain.services import records_service as rs
from app.domain.services.quest_generation_service import FAMILY_LABELS
from app.infrastructure.config.settings import settings
from app.infrastructure.db.repositories.records_repository import RecordsRepository
from app.infrastructure.db.unit_of_work import atomic
from app.infrastructure.encounters.farm_zone_loader import list_zones

PARIS = ZoneInfo("Europe/Paris")
_logger = logging.getLogger(__name__)


def paris_day(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(PARIS).date()


def family_label(family: str) -> str:
    """Le nom de la famille au pluriel : « démons », « morts-vivants »…"""
    return FAMILY_LABELS.get(family, family)


def open_families() -> list[tuple[str, str]]:
    """Familles des zones OUVERTES, dans l'ordre des zones : (code, nom)."""
    seen: list[tuple[str, str]] = []
    for zone in list_zones():
        if not int(zone.get("channel_id", 0) or 0):
            continue
        for family in zone.get("families") or ():
            if family and family not in {code for code, _ in seen}:
                seen.append((family, family_label(family)))
    return seen


def records_list() -> list[rs.RecordDef]:
    return rs.all_records(open_families())


# ------------------------------------------------------------- un combat

def track_fight(session: Session, encounter, result) -> None:
    """Exploits d'un combat de zone. Une lune (pleine, de sang, éclipse) rend
    les monstres plus forts : ces combats ne comptent pas."""
    if getattr(encounter, "lunar", None) is not None:
        return
    peaks = rs.fight_peaks(getattr(result, "turn_logs", None), getattr(result, "contributions", None))
    fighters = {p.player_id for p in encounter.participants.values()}
    detail = getattr(encounter, "mob_names", "") or ""
    now = datetime.now(UTC)
    try:
        with session.begin_nested():
            repo = RecordsRepository(session)
            for player_id, values in peaks.items():
                if player_id in fighters:
                    for code, value in values.items():
                        repo.raise_best(player_id, code, value, now, detail)
    except Exception:  # noqa: BLE001 — un record ne coûte jamais les récompenses
        _logger.exception("records du combat non enregistrés")


# ------------------------------------------------------------- les records

def _all_entries(session: Session, records: list[rs.RecordDef]) -> dict[str, list[rs.Entry]]:
    repo = RecordsRepository(session)
    entries: dict[str, list[rs.Entry]] = {}
    entries.update(repo.exploit_entries())
    entries.update(repo.defi_entries())
    entries[rs.TOWER.code] = repo.tower_entries()
    entries[rs.BOSS.code] = repo.boss_entries()
    families = [r.code.removeprefix("chasse_") for r in records if r.category == "chasse"]
    entries.update(repo.hunt_entries(families))
    wanted = {r.code for r in records}
    return {code: found for code, found in entries.items() if code in wanted}


def excluded_players(session: Session) -> set[int]:
    """Comptes admin : ils peuvent tout se donner, ils n'entrent pas dans les records."""
    return RecordsRepository(session).player_ids_for_discord(settings.admin_ids)


def current_holdings(session: Session, records: list[rs.RecordDef]) -> dict[str, rs.Entry]:
    excluded = excluded_players(session)
    entries = _all_entries(session, records)
    return rs.holdings({code: [e for e in found if e.player_id not in excluded]
                        for code, found in entries.items()})


@dataclass
class NightReport:
    day: date
    records: list[rs.RecordDef]
    held: dict[str, rs.Entry]
    changes: list[rs.Change]
    standings: list[rs.Standing]
    #: Titre → détenteur cette nuit, et ceux qui le reçoivent cette nuit.
    titles: dict[str, int | None]
    new_titles: dict[str, int] = field(default_factory=dict)
    #: player_id → (identifiant Discord, nom affiché).
    names: dict[int, tuple[int, str]] = field(default_factory=dict)
    first: bool = False
    message_id: int | None = None


def run_night(session: Session, now: datetime | None = None) -> NightReport | None:
    """La mise à jour de la nuit, une fois par jour de Paris (None : déjà faite)."""
    day = paris_day(now)
    with atomic(session):
        repo = RecordsRepository(session)
        board = repo.board()
        if board.last_day == day:
            return None
        records = records_list()
        before = repo.holders()
        held = current_holdings(session, records)
        standings = rs.ranking(held)
        titles = rs.title_awards(standings)
        exclusive = ExclusiveTitleService(session)
        new_titles = {}
        for code, player_id in titles.items():
            if player_id is None:
                exclusive.revoke(code)
            elif exclusive.award_to(code, player_id):
                new_titles[code] = player_id
        moved = rs.changes(records, before, held)
        repo.save_holders(held)
        repo.mark_night(day)
        people = {e.player_id for e in held.values()} | {c.old.player_id for c in moved if c.old}
        return NightReport(day=day, records=records, held=held, changes=moved, standings=standings,
                           titles=titles, new_titles=new_titles, names=repo.names(people),
                           first=not before, message_id=board.message_id)


def set_board_message(session: Session, message_id: int | None) -> None:
    with atomic(session):
        RecordsRepository(session).set_message(message_id)


@dataclass
class PersonalView:
    records: list[rs.RecordDef]
    #: Détenteurs publiés la nuit dernière.
    held: dict[str, rs.Entry]
    #: Les meilleurs du joueur, en direct.
    mine: dict[str, rs.Entry]
    names: dict[int, tuple[int, str]]
    excluded: bool = False


def personal(session: Session, player_id: int) -> PersonalView:
    records = records_list()
    repo = RecordsRepository(session)
    held = repo.holders()
    mine = {}
    for code, found in _all_entries(session, records).items():
        for entry in found:
            if entry.player_id == player_id:
                mine[code] = entry
    return PersonalView(records=records, held=held, mine=mine,
                        names=repo.names({e.player_id for e in held.values()}),
                        excluded=player_id in excluded_players(session))
