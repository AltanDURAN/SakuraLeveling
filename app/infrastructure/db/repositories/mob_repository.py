import random

from sqlalchemy import select
from datetime import datetime, UTC
from sqlalchemy.orm import Session

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

    def get_random(self) -> MobDefinition | None:
        stmt = select(MobDefinitionModel)
        models = self.session.execute(stmt).scalars().all()

        if not models:
            return None

        weights = [model.spawn_weight for model in models]
        model = random.choices(models, weights=weights, k=1)[0]

        return self._to_domain(model)

    def create(
        self,
        code: str,
        name: str,
        description: str,
        max_hp: int,
        attack: int,
        defense: int,
        speed: int,
        xp_reward: int,
        gold_reward: int,
        image_name: str,
        crit_chance: int = 0,
        crit_damage: int = 100,
        dodge: int = 0,
        hp_regeneration: int = 0,
        spawn_weight: int = 1,
        loot_table: list[dict] | None = None,
        current_hp: int | None = None,
    ) -> MobDefinition:
        if current_hp is None:
            current_hp = max_hp

        model = MobDefinitionModel(
            code=code,
            name=name,
            description=description,
            image_name=image_name,
            max_hp=max_hp,
            current_hp=current_hp,
            attack=attack,
            defense=defense,
            speed=speed,
            xp_reward=xp_reward,
            gold_reward=gold_reward,
            crit_chance=crit_chance,
            crit_damage=crit_damage,
            dodge=dodge,
            hp_regeneration=hp_regeneration,
            spawn_weight=spawn_weight,
            loot_table_json=loot_table,
        )

        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)

        return self._to_domain(model)

    def update_current_hp(self, code: str, current_hp: int) -> None:
        stmt = select(MobDefinitionModel).where(MobDefinitionModel.code == code)
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return

        model.current_hp = max(0, min(current_hp, model.max_hp))
        self.session.commit()

    def reset_current_hp(self, code: str) -> None:
        stmt = select(MobDefinitionModel).where(MobDefinitionModel.code == code)
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return

        model.current_hp = model.max_hp
        self.session.commit()

    def _to_domain(self, model: MobDefinitionModel) -> MobDefinition:
        return MobDefinition(
            id=model.id,
            code=model.code,
            name=model.name,
            description=model.description,
            image_name=model.image_name,
            max_hp=model.max_hp,
            current_hp=model.current_hp,
            attack=model.attack,
            defense=model.defense,
            speed=model.speed,
            xp_reward=model.xp_reward,
            gold_reward=model.gold_reward,
            spawn_weight=model.spawn_weight,
            crit_chance=model.crit_chance,
            crit_damage=model.crit_damage,
            dodge=model.dodge,
            hp_regeneration=model.hp_regeneration,
            loot_table=model.loot_table_json,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
    
    def update_by_code(
        self,
        code: str,
        name: str,
        description: str,
        max_hp: int,
        current_hp: int,
        attack: int,
        defense: int,
        speed: int,
        crit_chance: int,
        crit_damage: int,
        dodge: int,
        hp_regeneration: int,
        xp_reward: int,
        gold_reward: int,
        image_name: str | None,
        spawn_weight: int,
        loot_table: list[dict] | None = None,
    ):
        stmt = select(MobDefinitionModel).where(MobDefinitionModel.code == code)
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        model.name = name
        model.description = description
        model.max_hp = max_hp
        model.current_hp = current_hp
        model.attack = attack
        model.defense = defense
        model.speed = speed
        model.crit_chance = crit_chance
        model.crit_damage = crit_damage
        model.dodge = dodge
        model.hp_regeneration = hp_regeneration
        model.xp_reward = xp_reward
        model.gold_reward = gold_reward
        model.image_name = image_name
        model.spawn_weight = spawn_weight
        model.loot_table_json = loot_table
        model.updated_at = datetime.now(UTC)

        self.session.commit()
        self.session.refresh(model)

        return self._to_domain(model)