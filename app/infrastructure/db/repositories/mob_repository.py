from sqlalchemy import select
from sqlalchemy.orm import Session
import random

from app.domain.entities.mob_definition import MobDefinition
from app.infrastructure.db.models.mob_model import MobDefinitionModel

class MobRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_code(self, code: str) -> MobDefinition | None:
        stmt = select(MobDefinitionModel).where(MobDefinitionModel.code == code)
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        return self._to_domain(model)

    def create(
        self,
        code: str,
        name: str,
        description: str,
        max_hp: int,
        attack: int,
        defense: int,
        xp_reward: int,
        gold_reward: int,
        spawn_weight: int = 1,
        loot_table: list[dict] | None = None,
        image_url: str | None = None,
    ) -> MobDefinition:
        model = MobDefinitionModel(
            code=code,
            name=name,
            description=description,
            max_hp=max_hp,
            attack=attack,
            defense=defense,
            xp_reward=xp_reward,
            gold_reward=gold_reward,
            spawn_weight=spawn_weight,
            loot_table_json=loot_table,
            image_url=image_url,
        )

        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)

        return self._to_domain(model)

    def _to_domain(self, model: MobDefinitionModel) -> MobDefinition:
        return MobDefinition(
            id=model.id,
            code=model.code,
            name=model.name,
            description=model.description,
            max_hp=model.max_hp,
            attack=model.attack,
            defense=model.defense,
            xp_reward=model.xp_reward,
            gold_reward=model.gold_reward,
            spawn_weight=model.spawn_weight,
            loot_table=model.loot_table_json,
            image_url=model.image_url,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
        
    def get_random(self) -> MobDefinition | None:
        stmt = select(MobDefinitionModel)
        models = self.session.execute(stmt).scalars().all()

        if not models:
            return None

        weights = [getattr(m, "spawn_weight", 1) for m in models]
        model = random.choices(models, weights=weights, k=1)[0]

        return self._to_domain(model)