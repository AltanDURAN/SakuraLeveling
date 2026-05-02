"""Repository pour les world bosses et leurs participations.

Convention : un seul boss "active" en DB à la fois. Quand le boss est tué,
son statut passe à "defeated" et la prochaine commande /boss spawn (admin)
peut créer un nouveau boss. Les participations sont rattachées au boss
spécifique (FK on delete=cascade) — on garde l'historique des morts.
"""

from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.world_boss import (
    WorldBoss,
    WorldBossParticipation,
    WorldBossStatus,
)
from app.infrastructure.db.models.world_boss_model import (
    WorldBossModel,
    WorldBossParticipationModel,
)


class WorldBossRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---------- boss CRUD ----------

    def get_active(self) -> WorldBoss | None:
        stmt = (
            select(WorldBossModel)
            .where(WorldBossModel.status == WorldBossStatus.ACTIVE.value)
            .order_by(WorldBossModel.spawned_at.desc())
            .limit(1)
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        return self._to_domain(model) if model else None

    def get_by_id(self, boss_id: int) -> WorldBoss | None:
        model = self.session.get(WorldBossModel, boss_id)
        return self._to_domain(model) if model else None

    def get_latest_defeated(self) -> WorldBoss | None:
        """Le dernier boss défait (utilisé pour le cooldown de respawn 7j)."""
        stmt = (
            select(WorldBossModel)
            .where(WorldBossModel.status == WorldBossStatus.DEFEATED.value)
            .order_by(WorldBossModel.defeated_at.desc())
            .limit(1)
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        return self._to_domain(model) if model else None

    def create(
        self,
        code: str,
        name: str,
        image_name: str,
        max_hp: int,
        attack: int,
        defense: int,
        speed: int,
        crit_chance: int = 0,
        crit_damage: int = 100,
        dodge: int = 0,
        hp_regeneration: int = 0,
    ) -> WorldBoss:
        now = datetime.now(UTC)
        model = WorldBossModel(
            code=code,
            name=name,
            image_name=image_name,
            max_hp=max_hp,
            current_hp=max_hp,
            attack=attack,
            defense=defense,
            speed=speed,
            crit_chance=crit_chance,
            crit_damage=crit_damage,
            dodge=dodge,
            hp_regeneration=hp_regeneration,
            status=WorldBossStatus.ACTIVE.value,
            spawned_at=now,
        )
        self.session.add(model)
        self.session.commit()
        return self._to_domain(model)

    def apply_damage(self, boss_id: int, damage: int) -> int:
        """Décrémente current_hp atomiquement. Retourne les HP restants."""
        model = self.session.get(WorldBossModel, boss_id)
        if model is None:
            return 0
        model.current_hp = max(0, model.current_hp - damage)
        self.session.commit()
        return model.current_hp

    def mark_defeated(self, boss_id: int) -> None:
        model = self.session.get(WorldBossModel, boss_id)
        if model is None:
            return
        model.status = WorldBossStatus.DEFEATED.value
        model.defeated_at = datetime.now(UTC)
        model.current_hp = 0
        self.session.commit()

    def set_message_id(self, boss_id: int, message_id: int) -> None:
        model = self.session.get(WorldBossModel, boss_id)
        if model is None:
            return
        model.channel_message_id = message_id
        self.session.commit()

    # ---------- participations ----------

    def get_participation(
        self, boss_id: int, player_id: int
    ) -> WorldBossParticipation | None:
        stmt = select(WorldBossParticipationModel).where(
            WorldBossParticipationModel.boss_id == boss_id,
            WorldBossParticipationModel.player_id == player_id,
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        return self._participation_to_domain(model) if model else None

    def upsert_participation(
        self, boss_id: int, player_id: int, joined: bool = True
    ) -> WorldBossParticipation:
        existing = self.session.execute(
            select(WorldBossParticipationModel).where(
                WorldBossParticipationModel.boss_id == boss_id,
                WorldBossParticipationModel.player_id == player_id,
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is None:
            model = WorldBossParticipationModel(
                boss_id=boss_id,
                player_id=player_id,
                joined=joined,
                damage_dealt=0,
                damage_tanked=0,
                hp_healed=0,
                fights_count=0,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
        else:
            existing.joined = joined
            existing.updated_at = now
            model = existing
        self.session.commit()
        return self._participation_to_domain(model)

    def add_combat_metrics(
        self,
        boss_id: int,
        player_id: int,
        damage_dealt: int,
        damage_tanked: int,
        hp_healed: int,
    ) -> None:
        existing = self.session.execute(
            select(WorldBossParticipationModel).where(
                WorldBossParticipationModel.boss_id == boss_id,
                WorldBossParticipationModel.player_id == player_id,
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is None:
            existing = WorldBossParticipationModel(
                boss_id=boss_id,
                player_id=player_id,
                joined=True,
                damage_dealt=damage_dealt,
                damage_tanked=damage_tanked,
                hp_healed=hp_healed,
                fights_count=1,
                created_at=now,
                updated_at=now,
            )
            self.session.add(existing)
        else:
            existing.damage_dealt += damage_dealt
            existing.damage_tanked += damage_tanked
            existing.hp_healed += hp_healed
            existing.fights_count += 1
            existing.updated_at = now
        self.session.commit()

    def list_joined_participants(self, boss_id: int) -> list[WorldBossParticipation]:
        stmt = select(WorldBossParticipationModel).where(
            WorldBossParticipationModel.boss_id == boss_id,
            WorldBossParticipationModel.joined.is_(True),
        )
        return [
            self._participation_to_domain(m)
            for m in self.session.execute(stmt).scalars().all()
        ]

    def count_joined(self, boss_id: int) -> int:
        return len(self.list_joined_participants(boss_id))

    def list_participations_with_metrics(
        self, boss_id: int
    ) -> list[WorldBossParticipation]:
        """Liste tous les joueurs ayant combattu (fights_count > 0), peu
        importe leur statut joined. Utilisé pour les récompenses."""
        stmt = select(WorldBossParticipationModel).where(
            WorldBossParticipationModel.boss_id == boss_id,
            WorldBossParticipationModel.fights_count > 0,
        )
        return [
            self._participation_to_domain(m)
            for m in self.session.execute(stmt).scalars().all()
        ]

    # ---------- conversions ----------

    def _to_domain(self, model: WorldBossModel) -> WorldBoss:
        return WorldBoss(
            id=model.id,
            code=model.code,
            name=model.name,
            image_name=model.image_name,
            max_hp=model.max_hp,
            current_hp=model.current_hp,
            attack=model.attack,
            defense=model.defense,
            speed=model.speed,
            crit_chance=model.crit_chance,
            crit_damage=model.crit_damage,
            dodge=model.dodge,
            hp_regeneration=model.hp_regeneration,
            status=WorldBossStatus(model.status),
            spawned_at=model.spawned_at,
            defeated_at=model.defeated_at,
            channel_message_id=model.channel_message_id,
        )

    def _participation_to_domain(
        self, model: WorldBossParticipationModel
    ) -> WorldBossParticipation:
        return WorldBossParticipation(
            id=model.id,
            boss_id=model.boss_id,
            player_id=model.player_id,
            joined=model.joined,
            damage_dealt=model.damage_dealt,
            damage_tanked=model.damage_tanked,
            hp_healed=model.hp_healed,
            fights_count=model.fights_count,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
