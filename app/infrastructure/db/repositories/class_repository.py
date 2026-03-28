from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.class_definition import ClassDefinition
from app.domain.entities.player_class_state import PlayerClassState
from app.infrastructure.db.models.class_model import ClassDefinitionModel
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel


class ClassRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_code(self, code: str) -> ClassDefinition | None:
        stmt = select(ClassDefinitionModel).where(ClassDefinitionModel.code == code)
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        return self._to_class_domain(model)

    def list_all(self) -> list[ClassDefinition]:
        stmt = select(ClassDefinitionModel).order_by(ClassDefinitionModel.id.asc())
        models = self.session.execute(stmt).scalars().all()
        return [self._to_class_domain(model) for model in models]

    def create(
        self,
        code: str,
        name: str,
        description: str,
        stat_bonuses: dict | None = None,
    ) -> ClassDefinition:
        model = ClassDefinitionModel(
            code=code,
            name=name,
            description=description,
            stat_bonuses_json=stat_bonuses,
        )

        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)

        return self._to_class_domain(model)

    def get_player_class_state(self, player_id: int) -> PlayerClassState | None:
        model = self.session.get(PlayerClassStateModel, player_id)
        if model is None:
            return None

        return self._to_player_class_state_domain(model)

    def get_or_create_player_class_state(self, player_id: int) -> PlayerClassState:
        model = self.session.get(PlayerClassStateModel, player_id)
        if model is None:
            now = datetime.utcnow()
            model = PlayerClassStateModel(
                player_id=player_id,
                current_class_id=None,
                unlocked_at=None,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)

        return self._to_player_class_state_domain(model)

    def set_player_class(self, player_id: int, class_id: int) -> None:
        model = self.session.get(PlayerClassStateModel, player_id)
        now = datetime.utcnow()

        if model is None:
            model = PlayerClassStateModel(
                player_id=player_id,
                current_class_id=class_id,
                unlocked_at=now,
                created_at=now,
                updated_at=now,
            )
            self.session.add(model)
        else:
            model.current_class_id = class_id
            if model.unlocked_at is None:
                model.unlocked_at = now
            model.updated_at = now

        self.session.commit()

    def get_current_class_for_player(self, player_id: int) -> ClassDefinition | None:
        state = self.session.get(PlayerClassStateModel, player_id)
        if state is None or state.current_class_id is None:
            return None

        class_model = self.session.get(ClassDefinitionModel, state.current_class_id)
        if class_model is None:
            return None

        return self._to_class_domain(class_model)

    def _to_class_domain(self, model: ClassDefinitionModel) -> ClassDefinition:
        return ClassDefinition(
            id=model.id,
            code=model.code,
            name=model.name,
            description=model.description,
            stat_bonuses=model.stat_bonuses_json,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_player_class_state_domain(self, model: PlayerClassStateModel) -> PlayerClassState:
        return PlayerClassState(
            player_id=model.player_id,
            current_class_id=model.current_class_id,
            unlocked_at=model.unlocked_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )