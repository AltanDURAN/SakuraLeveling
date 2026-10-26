from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.player import Player
from app.domain.entities.player_profile import PlayerProfile
from app.domain.entities.player_progression import PlayerProgression
from app.domain.entities.player_resources import PlayerResources
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.repositories.element_affinity_repository import (
    ElementAffinityRepository,
)


class PlayerRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_discord_id(self, discord_id: int) -> PlayerProfile | None:
        stmt = (
            select(PlayerModel)
            .options(
                joinedload(PlayerModel.progression),
                joinedload(PlayerModel.resources),
            )
            .where(PlayerModel.discord_id == discord_id)
        )

        player_model = self.session.execute(stmt).scalar_one_or_none()

        if player_model is None:
            return None

        return self._to_domain(player_model)

    def get_profile_by_player_id(self, player_id: int) -> PlayerProfile | None:
        stmt = (
            select(PlayerModel)
            .options(
                joinedload(PlayerModel.progression),
                joinedload(PlayerModel.resources),
            )
            .where(PlayerModel.id == player_id)
        )
        player_model = self.session.execute(stmt).scalar_one_or_none()
        return self._to_domain(player_model) if player_model else None

    def create_player(self, discord_id: int, username: str, display_name: str) -> PlayerProfile:
        now = datetime.now(UTC)

        player_model = PlayerModel(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )

        progression_model = PlayerProgressionModel(
            level=1,
            xp=0,
            skill_points=0,
            created_at=now,
            updated_at=now,
        )

        resource_model = PlayerResourceModel(
            gold=0,
            created_at=now,
            updated_at=now,
        )

        player_model.progression = progression_model
        player_model.resources = resource_model

        self.session.add(player_model)
        self.session.commit()
        self.session.refresh(player_model)

        self._ensure_elemental_setup(player_model.id)
        self.session.refresh(player_model)

        return self._to_domain(player_model)

    def _ensure_elemental_setup(self, player_id: int) -> None:
        """Garantit que le joueur a ses 8 affinités élémentaires (tirées
        aléatoirement 0..10 à la création — la montée jusqu'à 100 se fait en
        farmant des essences) et 2 compétences de départ. Idempotent : sert
        aussi de backfill paresseux pour les joueurs antérieurs au système.
        L'élément d'attaque dérive de la compétence offensive équipée (plus de
        champ `active_element` — source de vérité unique)."""
        ElementAffinityRepository(self.session).init_for_player(player_id, high=10)

        player_model = self.session.get(PlayerModel, player_id)
        if player_model is None:
            return

        affinities = ElementAffinityRepository(self.session).get_affinities(player_id)
        best = (
            max(affinities.items(), key=lambda kv: kv[1])[0]
            if affinities else None
        )

        changed = False
        # Compétences de départ : offensive + support de l'élément préféré.
        if best and not player_model.skill_slot_1 and not player_model.skill_slot_2:
            player_model.skill_slot_1 = f"{best}_offensive"
            player_model.skill_slot_2 = f"{best}_support"
            changed = True
        if changed:
            player_model.updated_at = datetime.now(UTC)
            self.session.commit()

    def get_or_create_by_discord_id(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> PlayerProfile:
        existing = self.get_by_discord_id(discord_id)

        if existing is not None:
            self._update_identity_metadata(existing.player.id, username, display_name)
            self._ensure_elemental_setup(existing.player.id)  # backfill paresseux
            return self.get_by_discord_id(discord_id)  # refreshed

        return self.create_player(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )
        
    def add_xp(self, player_id: int, amount: int) -> None:
        progression = self.session.get(PlayerProgressionModel, player_id)
        if progression is None:
            return

        # Clamp à 0 : aucun chemin légitime ne déduit de l'XP ; protège contre
        # un solde négatif si un admin passe un amount<0 par erreur.
        progression.xp = max(0, progression.xp + amount)
        progression.updated_at = datetime.now(UTC)
        self.session.commit()

    def add_gold(self, player_id: int, gold: int, commit: bool = True) -> None:
        resources = self.session.get(PlayerResourceModel, player_id)
        if resources is None:
            return

        # Clamp à 0 : les déductions légitimes (buy_from_shop, transfer, accept_trade,
        # marketplace) vérifient le solde en amont — le clamp est de la défense en
        # profondeur contre une race ou un appel admin malformé.
        resources.gold = max(0, resources.gold + gold)
        resources.updated_at = datetime.now(UTC)
        self.session.commit() if commit else self.session.flush()

    def set_gold(self, player_id: int, gold: int) -> None:
        resources = self.session.get(PlayerResourceModel, player_id)
        if resources is None:
            return

        resources.gold = max(0, gold)
        resources.updated_at = datetime.now(UTC)
        self.session.commit()

    def increment_daily_streak(self, player_id: int) -> int:
        """Incrémente la série /daily du joueur de 1 et renvoie la nouvelle valeur."""
        resources = self.session.get(PlayerResourceModel, player_id)
        if resources is None:
            return 0

        resources.daily_streak += 1
        resources.updated_at = datetime.now(UTC)
        self.session.commit()
        return resources.daily_streak

    def set_daily_streak(self, player_id: int, streak: int) -> None:
        resources = self.session.get(PlayerResourceModel, player_id)
        if resources is None:
            return
        resources.daily_streak = max(0, streak)
        resources.updated_at = datetime.now(UTC)
        self.session.commit()

    def set_combat_tactic(self, player_id: int, tactic: str) -> None:
        player_model = self.session.get(PlayerModel, player_id)
        if player_model is None:
            return
        player_model.combat_tactic = tactic
        player_model.updated_at = datetime.now(UTC)
        self.session.commit()

    def set_panoplie_bonus(self, player_id: int, bonus_type: str) -> None:
        player_model = self.session.get(PlayerModel, player_id)
        if player_model is None:
            return
        player_model.panoplie_bonus = bonus_type
        player_model.updated_at = datetime.now(UTC)
        self.session.commit()

    def get_combat_tactics(self, player_ids: list[int]) -> dict[int, str]:
        """Tactiques de plusieurs joueurs en une requête (combats de groupe)."""
        if not player_ids:
            return {}
        rows = self.session.execute(
            select(PlayerModel.id, PlayerModel.combat_tactic).where(PlayerModel.id.in_(player_ids))
        ).all()
        return {pid: (tactic or "egoiste") for pid, tactic in rows}

    def add_skill_points(self, player_id: int, amount: int) -> None:
        progression = self.session.get(PlayerProgressionModel, player_id)
        if progression is None:
            return
        progression.skill_points = max(0, progression.skill_points + amount)
        progression.updated_at = datetime.now(UTC)
        self.session.commit()

    def set_skill_points(self, player_id: int, amount: int) -> None:
        progression = self.session.get(PlayerProgressionModel, player_id)
        if progression is None:
            return
        progression.skill_points = max(0, amount)
        progression.updated_at = datetime.now(UTC)
        self.session.commit()

    def allocate_stat_point(
        self, player_id: int, target: str, amount: int = 1,
    ) -> bool:
        """Investit `amount` points de stats dans `target`.

        Tout ou rien : si le joueur n'a pas assez de points disponibles, rien
        n'est écrit. Évite qu'un double-clic place deux fois le même point.
        """
        from app.domain.value_objects.base_stats import STAT_POINT_GAIN

        if target not in STAT_POINT_GAIN or amount <= 0:
            return False
        progression = self.session.get(PlayerProgressionModel, player_id)
        if progression is None or progression.stat_points < amount:
            return False

        column = {
            "attack": "points_attack",
            "defense": "points_defense",
            "max_hp": "points_max_hp",
        }[target]
        setattr(progression, column, getattr(progression, column) + amount)
        progression.stat_points -= amount
        progression.updated_at = datetime.now(UTC)
        self.session.commit()
        return True

    def apply_progression(
        self,
        player_id: int,
        new_level: int,
        new_xp: int,
        new_skill_points: int,
        new_stat_points: int | None = None,
    ) -> None:
        progression = self.session.get(PlayerProgressionModel, player_id)
        if progression is None:
            return

        if new_stat_points is not None:
            progression.stat_points = new_stat_points
        progression.level = new_level
        progression.xp = new_xp
        progression.skill_points = new_skill_points
        progression.updated_at = datetime.now(UTC)

        self.session.commit()

    def _update_identity_metadata(self, player_id: int, username: str, display_name: str) -> None:
        player_model = self.session.get(PlayerModel, player_id)
        if player_model is None:
            return

        player_model.username = username
        player_model.display_name = display_name
        player_model.last_seen_at = datetime.now(UTC)
        player_model.updated_at = datetime.now(UTC)

        self.session.commit()

    def list_all_profiles(self) -> list[PlayerProfile]:
        stmt = select(PlayerModel).options(
            joinedload(PlayerModel.progression),
            joinedload(PlayerModel.resources),
        )
        models = self.session.execute(stmt).scalars().all()
        return [self._to_domain(model) for model in models]

    def _to_domain(self, player_model: PlayerModel) -> PlayerProfile:
        player = Player(
            id=player_model.id,
            discord_id=player_model.discord_id,
            username=player_model.username,
            display_name=player_model.display_name,
            created_at=player_model.created_at,
            updated_at=player_model.updated_at,
            last_seen_at=player_model.last_seen_at,
            skill_slot_1=player_model.skill_slot_1,
            skill_slot_2=player_model.skill_slot_2,
            combat_tactic=getattr(player_model, "combat_tactic", None) or "egoiste",
            panoplie_bonus=getattr(player_model, "panoplie_bonus", None) or "attack",
        )

        progression = PlayerProgression(
            player_id=player_model.progression.player_id,
            level=player_model.progression.level,
            xp=player_model.progression.xp,
            skill_points=player_model.progression.skill_points,
            created_at=player_model.progression.created_at,
            updated_at=player_model.progression.updated_at,
            stat_points=player_model.progression.stat_points,
            points_attack=player_model.progression.points_attack,
            points_defense=player_model.progression.points_defense,
            points_max_hp=player_model.progression.points_max_hp,
        )

        resources = PlayerResources(
            player_id=player_model.resources.player_id,
            gold=player_model.resources.gold,
            daily_streak=player_model.resources.daily_streak,
            created_at=player_model.resources.created_at,
            updated_at=player_model.resources.updated_at,
        )

        return PlayerProfile(
            player=player,
            progression=progression,
            resources=resources,
        )