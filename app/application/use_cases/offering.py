"""Offrande commune (`/offrande`) : la jauge, un don, la bénédiction active.

Règles pures dans `app/domain/services/offering_service.py`, divinités dans
`deities.json`. Les effets de la bénédiction sont lus par les systèmes
concernés via `active_blessing` (combats de zone, régénération, meutes,
tickets de tour).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, UTC
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.player_profile import PlayerProfile
from app.domain.services import offering_service as osvc
from app.infrastructure.db.models.offering_model import OfferingContributionModel, OfferingStateModel
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.unit_of_work import atomic
from app.infrastructure.offering import deity_loader

_PARIS = ZoneInfo("Europe/Paris")


class OfferingError(Exception):
    """Don refusé (message pour le joueur)."""


@dataclass(frozen=True)
class OfferingStatus:
    target: int
    contributed: int
    open: bool                      # False : déjà remplie aujourd'hui
    fills: int
    blessing: osvc.Deity | None     # bénédiction active
    blessing_until: datetime | None
    top: list[tuple[str, int]]      # (nom, montant) des donateurs de la jauge en cours
    mine: int                       # ce que ce joueur a versé dans la jauge en cours


@dataclass(frozen=True)
class OfferingOutcome:
    given: int
    status: OfferingStatus
    invoked: osvc.Deity | None      # la divinité invoquée par CE don (jauge remplie)


def offering_day(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(_PARIS).date()


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _state(session: Session, now: datetime | None = None) -> OfferingStateModel:
    """La jauge, prix mis à jour des jours passés sans remplissage."""
    row = session.get(OfferingStateModel, 1)
    today = offering_day(now)
    if row is None:
        row = OfferingStateModel(id=1, cycle=1, target=osvc.BASE_TARGET, contributed=0, fills=0,
                                 priced_on=today)
        session.add(row)
        session.flush()
        return row
    if row.priced_on is None:
        row.priced_on = today
    elif row.priced_on < today:
        # Jours écoulés depuis la dernière mise à jour du prix, sans compter
        # celui du dernier remplissage.
        missed = (today - row.priced_on).days
        if row.filled_on == row.priced_on:
            missed -= 1
        row.target = osvc.decayed(row.target, missed)
        row.priced_on = today
    session.flush()
    return row


def active_blessing(session: Session, now: datetime | None = None) -> osvc.Deity | None:
    """La divinité qui bénit le serveur en ce moment, ou None."""
    row = session.get(OfferingStateModel, 1)
    if row is None or row.blessing_until is None or row.blessing_until <= _naive(now or datetime.now(UTC)):
        return None
    return deity_loader.get_deity(row.deity_code)


def blessing_window(session: Session) -> tuple[datetime, datetime] | None:
    """(début, fin) de la bénédiction en cours ou passée la plus récente."""
    row = session.get(OfferingStateModel, 1)
    if row is None or row.blessed_at is None or row.blessing_until is None:
        return None
    return row.blessed_at.replace(tzinfo=UTC), row.blessing_until.replace(tzinfo=UTC)


def status(session: Session, profile: PlayerProfile | None = None,
           now: datetime | None = None) -> OfferingStatus:
    row = _state(session, now)
    top = session.execute(
        select(PlayerModel.display_name, OfferingContributionModel.amount)
        .join(PlayerModel, PlayerModel.id == OfferingContributionModel.player_id)
        .where(OfferingContributionModel.cycle == row.cycle)
        .order_by(OfferingContributionModel.amount.desc())
        .limit(5)
    ).all()
    mine = 0
    if profile is not None:
        own = session.get(OfferingContributionModel, (row.cycle, profile.player.id))
        mine = own.amount if own is not None else 0
    blessing = active_blessing(session, now)
    return OfferingStatus(
        target=row.target, contributed=row.contributed,
        open=row.filled_on != offering_day(now), fills=row.fills,
        blessing=blessing,
        blessing_until=row.blessing_until.replace(tzinfo=UTC) if blessing and row.blessing_until else None,
        top=[(name, amount) for name, amount in top], mine=mine,
    )


def contribute(session: Session, profile: PlayerProfile, amount: int,
               now: datetime | None = None) -> OfferingOutcome:
    """Verse `amount` or dans la jauge (au plus ce qu'il manque pour la
    remplir). Pleine : une divinité est invoquée pour 24 h."""
    now = now or datetime.now(UTC)
    player_id = profile.player.id
    with atomic(session):
        row = _state(session, now)
        if row.filled_on == offering_day(now):
            raise OfferingError("🙏 L'offrande a déjà été exaucée aujourd'hui : la jauge rouvre à minuit.")
        if amount <= 0:
            raise OfferingError("Le don doit être d'au moins 1 or.")
        players = PlayerRepository(session)
        gold = players.get_profile_by_player_id(player_id).resources.gold
        given = min(amount, gold, row.target - row.contributed)
        if given <= 0:
            raise OfferingError("💰 Tu n'as pas d'or à offrir.")
        players.add_gold(player_id, -given)
        row.contributed += given
        own = session.get(OfferingContributionModel, (row.cycle, player_id))
        if own is None:
            session.add(OfferingContributionModel(cycle=row.cycle, player_id=player_id, amount=given))
        else:
            own.amount += given

        invoked = None
        if row.contributed >= row.target:
            invoked = osvc.pick_deity(deity_loader.list_deities(), row.deity_code)
            row.deity_code = invoked.code if invoked else None
            row.blessed_at = _naive(now)
            row.blessing_until = _naive(now + timedelta(hours=osvc.BLESSING_HOURS))
            row.filled_on = offering_day(now)
            row.filled_by = player_id
            row.fills += 1
            row.cycle += 1
            row.contributed = 0
            row.target = osvc.grown(row.target)
        session.flush()
        return OfferingOutcome(given=given, status=status(session, profile, now), invoked=invoked)
