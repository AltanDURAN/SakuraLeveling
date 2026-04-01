from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.player_quest_state import PlayerQuestState
from app.domain.entities.quest_definition import QuestDefinition
from app.infrastructure.db.models.quest_model import PlayerQuestStateModel, QuestDefinitionModel


class QuestRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_definition_by_code(self, code: str) -> QuestDefinition | None:
        stmt = select(QuestDefinitionModel).where(QuestDefinitionModel.code == code)
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        return self._to_definition_domain(model)

    def list_definitions(self) -> list[QuestDefinition]:
        stmt = select(QuestDefinitionModel).order_by(QuestDefinitionModel.id.asc())
        models = self.session.execute(stmt).scalars().all()
        return [self._to_definition_domain(model) for model in models]

    def create_definition(
        self,
        code: str,
        name: str,
        description: str,
        objective_type: str,
        target_code: str,
        required_quantity: int,
        reward_gold: int,
        reward_xp: int,
        reward_items: list[dict] | None,
    ) -> QuestDefinition:
        model = QuestDefinitionModel(
            code=code,
            name=name,
            description=description,
            objective_type=objective_type,
            target_code=target_code,
            required_quantity=required_quantity,
            reward_gold=reward_gold,
            reward_xp=reward_xp,
            reward_items_json=reward_items,
        )

        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)

        return self._to_definition_domain(model)

    def get_or_create_player_quest_state(
        self,
        player_id: int,
        quest_definition_id: int,
    ) -> PlayerQuestState:
        stmt = select(PlayerQuestStateModel).where(
            PlayerQuestStateModel.player_id == player_id,
            PlayerQuestStateModel.quest_definition_id == quest_definition_id,
        )
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            now = datetime.now(timezone.utc)
            model = PlayerQuestStateModel(
                player_id=player_id,
                quest_definition_id=quest_definition_id,
                progress_quantity=0,
                is_completed=False,
                is_claimed=False,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)

        return self._to_state_domain(model)

    def list_player_quest_states(self, player_id: int) -> list[PlayerQuestState]:
        stmt = select(PlayerQuestStateModel).where(
            PlayerQuestStateModel.player_id == player_id
        )
        models = self.session.execute(stmt).scalars().all()
        return [self._to_state_domain(model) for model in models]

    def update_progress(
        self,
        player_id: int,
        quest_definition_id: int,
        progress_quantity: int,
        is_completed: bool,
    ) -> None:
        stmt = select(PlayerQuestStateModel).where(
            PlayerQuestStateModel.player_id == player_id,
            PlayerQuestStateModel.quest_definition_id == quest_definition_id,
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        if model is None:
            return

        model.progress_quantity = progress_quantity
        model.is_completed = is_completed
        model.updated_at = datetime.now(timezone.utc)
        self.session.commit()

    def mark_claimed(self, player_id: int, quest_definition_id: int) -> None:
        stmt = select(PlayerQuestStateModel).where(
            PlayerQuestStateModel.player_id == player_id,
            PlayerQuestStateModel.quest_definition_id == quest_definition_id,
        )
        model = self.session.execute(stmt).scalar_one_or_none()
        if model is None:
            return

        model.is_claimed = True
        model.updated_at = datetime.now(timezone.utc)
        self.session.commit()

    def _to_definition_domain(self, model: QuestDefinitionModel) -> QuestDefinition:
        return QuestDefinition(
            id=model.id,
            code=model.code,
            name=model.name,
            description=model.description,
            objective_type=model.objective_type,
            target_code=model.target_code,
            required_quantity=model.required_quantity,
            reward_gold=model.reward_gold,
            reward_xp=model.reward_xp,
            reward_items=model.reward_items_json,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_state_domain(self, model: PlayerQuestStateModel) -> PlayerQuestState:
        return PlayerQuestState(
            player_id=model.player_id,
            quest_definition_id=model.quest_definition_id,
            progress_quantity=model.progress_quantity,
            is_completed=model.is_completed,
            is_claimed=model.is_claimed,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )