"""Records du serveur : les meilleurs de chacun, lus dans les tables du jeu.

Exploits : `player_records` (tenus à chaque combat de zone). Défis, tour,
raid et chasse : les tables qui existent déjà (`role_trial_scores`,
`player_tower_progress`, `world_boss_participations`, `player_mob_kills`).
Aucune de ces méthodes ne valide la transaction : c'est à l'appelant.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.domain.services.records_service import DEFI_ROLES, Entry
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.records_model import (
    PlayerRecordModel,
    RecordBoardModel,
    RecordHolderModel,
)
from app.infrastructure.db.models.role_trial_model import RoleTrialScoreModel
from app.infrastructure.db.models.tower_progress_model import PlayerTowerProgressModel
from app.infrastructure.db.models.world_boss_model import WorldBossParticipationModel


def _naive(moment: datetime | None) -> datetime:
    """Dates comparables entre elles (la base les rend sans fuseau, en UTC)."""
    if moment is None:
        return datetime(2000, 1, 1)
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


class RecordsRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------ exploits
    def raise_best(self, player_id: int, code: str, value: int, at: datetime, detail: str = "") -> bool:
        """Garde la meilleure valeur du joueur (strictement meilleure)."""
        if value <= 0:
            return False
        row = self.session.execute(select(PlayerRecordModel).where(
            PlayerRecordModel.player_id == player_id, PlayerRecordModel.code == code)).scalar_one_or_none()
        if row is None:
            self.session.add(PlayerRecordModel(player_id=player_id, code=code, value=value,
                                               detail=detail[:120], achieved_at=_naive(at)))
            return True
        if value <= row.value:
            return False
        row.value, row.detail, row.achieved_at = value, detail[:120], _naive(at)
        return True

    def exploit_entries(self) -> dict[str, list[Entry]]:
        out: dict[str, list[Entry]] = {}
        for row in self.session.execute(select(PlayerRecordModel)).scalars():
            out.setdefault(row.code, []).append(Entry(row.player_id, row.value, _naive(row.achieved_at), row.detail))
        return out

    def player_exploits(self, player_id: int) -> dict[str, Entry]:
        rows = self.session.execute(select(PlayerRecordModel).where(PlayerRecordModel.player_id == player_id))
        return {r.code: Entry(r.player_id, r.value, _naive(r.achieved_at), r.detail) for r in rows.scalars()}

    # ------------------------------------------------- tables du jeu
    def defi_entries(self) -> dict[str, list[Entry]]:
        """Meilleur score de chaque joueur à chaque défi (atteint le plus tôt)."""
        best: dict[tuple[str, int], Entry] = {}
        for row in self.session.execute(select(RoleTrialScoreModel)).scalars():
            code = DEFI_ROLES.get(row.role)
            if code is None or (row.score or 0) <= 0:
                continue
            entry = Entry(row.player_id, row.score, _naive(row.updated_at))
            key = (code, row.player_id)
            current = best.get(key)
            if current is None or (entry.value, -entry.at.timestamp()) > (current.value, -current.at.timestamp()):
                best[key] = entry
        out: dict[str, list[Entry]] = {}
        for (code, _), entry in best.items():
            out.setdefault(code, []).append(entry)
        return out

    def tower_entries(self) -> list[Entry]:
        rows = self.session.execute(select(PlayerTowerProgressModel).where(PlayerTowerProgressModel.best_floor > 0))
        return [Entry(r.player_id, r.best_floor, _naive(r.best_at)) for r in rows.scalars()]

    def boss_entries(self) -> list[Entry]:
        """Le plus de dégâts de chaque joueur sur un même boss (une semaine)."""
        best: dict[int, Entry] = {}
        for row in self.session.execute(select(WorldBossParticipationModel)).scalars():
            if (row.damage_dealt or 0) <= 0:
                continue
            entry = Entry(row.player_id, row.damage_dealt, _naive(row.updated_at))
            current = best.get(row.player_id)
            if current is None or entry.value > current.value:
                best[row.player_id] = entry
        return list(best.values())

    def hunt_entries(self, families: list[str]) -> dict[str, list[Entry]]:
        """Monstres tués par famille et par joueur ; atteint à la dernière victoire."""
        rows = self.session.execute(
            select(PlayerMobKillModel.player_id, MobDefinitionModel.family,
                   func.sum(PlayerMobKillModel.kill_count), func.max(PlayerMobKillModel.updated_at))
            .join(MobDefinitionModel, MobDefinitionModel.code == PlayerMobKillModel.mob_code)
            .where(MobDefinitionModel.family.in_(families))
            .group_by(PlayerMobKillModel.player_id, MobDefinitionModel.family)
        ).all()
        out: dict[str, list[Entry]] = {}
        for player_id, family, total, last in rows:
            if total:
                out.setdefault(f"chasse_{family}", []).append(Entry(player_id, int(total), _naive(last)))
        return out

    def player_ids_for_discord(self, discord_ids) -> set[int]:
        ids = list(discord_ids)
        if not ids:
            return set()
        rows = self.session.execute(select(PlayerModel.id).where(PlayerModel.discord_id.in_(ids)))
        return set(rows.scalars())

    def names(self, player_ids) -> dict[int, tuple[int, str]]:
        """player_id → (discord_id, nom affiché)."""
        ids = list(player_ids)
        if not ids:
            return {}
        rows = self.session.execute(select(PlayerModel.id, PlayerModel.discord_id, PlayerModel.display_name)
                                    .where(PlayerModel.id.in_(ids)))
        return {pid: (discord_id, name) for pid, discord_id, name in rows}

    # ---------------------------------------------- détenteurs publiés
    def holders(self) -> dict[str, Entry]:
        rows = self.session.execute(select(RecordHolderModel)).scalars()
        return {r.code: Entry(r.player_id, r.value, _naive(r.achieved_at), r.detail) for r in rows}

    def save_holders(self, held: dict[str, Entry]) -> None:
        self.session.execute(delete(RecordHolderModel))
        for code, entry in held.items():
            self.session.add(RecordHolderModel(code=code, player_id=entry.player_id, value=entry.value,
                                               detail=entry.detail[:120], achieved_at=_naive(entry.at)))

    # ------------------------------------------------------- tableau
    def board(self) -> RecordBoardModel:
        row = self.session.get(RecordBoardModel, 1)
        if row is None:
            row = RecordBoardModel(id=1)
            self.session.add(row)
            self.session.flush()
        return row

    def mark_night(self, day: date) -> None:
        self.board().last_day = day

    def set_message(self, message_id: int | None) -> None:
        self.board().message_id = message_id
