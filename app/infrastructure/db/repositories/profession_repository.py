from datetime import datetime, UTC
from sqlalchemy import select

from app.domain.entities.profession_definition import ProfessionDefinition
from app.domain.entities.player_profession import PlayerProfession
from app.infrastructure.db.models.profession_model import (
    ProfessionDefinitionModel,
    PlayerProfessionModel,
)


class ProfessionRepository:
    def __init__(self, session):
        self.session = session

    def list_definitions(self) -> list[ProfessionDefinition]:
        models = self.session.execute(select(ProfessionDefinitionModel)).scalars().all()
        return [
            ProfessionDefinition(
                id=m.id,
                code=m.code,
                name=m.name,
                description=m.description,
                created_at=m.created_at,
                updated_at=m.updated_at,
            )
            for m in models
        ]

    def get_definition_by_code(self, code: str) -> ProfessionDefinition | None:
        model = self.session.execute(
            select(ProfessionDefinitionModel).where(ProfessionDefinitionModel.code == code)
        ).scalar_one_or_none()

        if not model:
            return None

        return ProfessionDefinition(
            id=model.id,
            code=model.code,
            name=model.name,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def get_or_create_player_profession(self, player_id: int, profession_id: int) -> PlayerProfession:
        model = self.session.execute(
            select(PlayerProfessionModel).where(
                PlayerProfessionModel.player_id == player_id,
                PlayerProfessionModel.profession_definition_id == profession_id,
            )
        ).scalar_one_or_none()

        if model is None:
            now = datetime.now(UTC)
            model = PlayerProfessionModel(
                player_id=player_id,
                profession_definition_id=profession_id,
                level=1,
                xp=0,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)

        return PlayerProfession(
            player_id=model.player_id,
            profession_definition_id=model.profession_definition_id,
            level=model.level,
            xp=model.xp,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def update_progress(self, player_id: int, profession_id: int, level: int, xp: int):
        model = self.session.execute(
            select(PlayerProfessionModel).where(
                PlayerProfessionModel.player_id == player_id,
                PlayerProfessionModel.profession_definition_id == profession_id,
            )
        ).scalar_one()

        model.level = level
        model.xp = xp
        model.updated_at = datetime.now(UTC)
        self.session.commit()
        
    def list_player_professions_with_definitions(
        self,
        player_id: int,
    ) -> list[tuple[str, PlayerProfession]]:
        stmt = select(PlayerProfessionModel).where(
            PlayerProfessionModel.player_id == player_id
        )
        player_profession_models = self.session.execute(stmt).scalars().all()

        results: list[tuple[str, PlayerProfession]] = []

        for model in player_profession_models:
            profession_definition = self.session.get(
                ProfessionDefinitionModel,
                model.profession_definition_id,
            )
            if profession_definition is None:
                continue

            results.append(
                (
                    profession_definition.code,
                    PlayerProfession(
                        player_id=model.player_id,
                        profession_definition_id=model.profession_definition_id,
                        level=model.level,
                        xp=model.xp,
                        created_at=model.created_at,
                        updated_at=model.updated_at,
                    ),
                )
            )

        return results