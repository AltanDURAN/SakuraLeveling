from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities.player import Player
from app.domain.entities.player_profile import PlayerProfile
from app.domain.entities.player_progression import PlayerProgression
from app.domain.entities.player_resources import PlayerResources
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel


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

    def create_player(self, discord_id: int, username: str, display_name: str) -> PlayerProfile:
        now = datetime.now(timezone.utc)

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

        return self._to_domain(player_model)

    def get_or_create_by_discord_id(
        self,
        discord_id: int,
        username: str,
        display_name: str,
    ) -> PlayerProfile:
        existing = self.get_by_discord_id(discord_id)

        if existing is not None:
            self._update_identity_metadata(existing.player.id, username, display_name)
            return self.get_by_discord_id(discord_id)  # refreshed

        return self.create_player(
            discord_id=discord_id,
            username=username,
            display_name=display_name,
        )
        
    def add_xp(self, player_id: int, xp: int) -> None:
        progression = self.session.get(PlayerProgressionModel, player_id)
        if progression is None:
            return

        progression.xp += xp
        progression.updated_at = datetime.now(timezone.utc)
        self.session.commit()

    def add_gold(self, player_id: int, gold: int) -> None:
        resources = self.session.get(PlayerResourceModel, player_id)
        if resources is None:
            return

        resources.gold += gold
        resources.updated_at = datetime.now(timezone.utc)
        self.session.commit()
        
    def apply_progression(
        self,
        player_id: int,
        new_level: int,
        new_xp: int,
        new_skill_points: int,
    ) -> None:
        progression = self.session.get(PlayerProgressionModel, player_id)
        if progression is None:
            return

        progression.level = new_level
        progression.xp = new_xp
        progression.skill_points = new_skill_points
        progression.updated_at = datetime.now(timezone.utc)

        self.session.commit()

    def _update_identity_metadata(self, player_id: int, username: str, display_name: str) -> None:
        player_model = self.session.get(PlayerModel, player_id)
        if player_model is None:
            return

        player_model.username = username
        player_model.display_name = display_name
        player_model.last_seen_at = datetime.now(timezone.utc)
        player_model.updated_at = datetime.now(timezone.utc)

        self.session.commit()

    def _to_domain(self, player_model: PlayerModel) -> PlayerProfile:
        player = Player(
            id=player_model.id,
            discord_id=player_model.discord_id,
            username=player_model.username,
            display_name=player_model.display_name,
            created_at=player_model.created_at,
            updated_at=player_model.updated_at,
            last_seen_at=player_model.last_seen_at,
        )

        progression = PlayerProgression(
            player_id=player_model.progression.player_id,
            level=player_model.progression.level,
            xp=player_model.progression.xp,
            skill_points=player_model.progression.skill_points,
            created_at=player_model.progression.created_at,
            updated_at=player_model.progression.updated_at,
        )

        resources = PlayerResources(
            player_id=player_model.resources.player_id,
            gold=player_model.resources.gold,
            created_at=player_model.resources.created_at,
            updated_at=player_model.resources.updated_at,
        )

        return PlayerProfile(
            player=player,
            progression=progression,
            resources=resources,
        )