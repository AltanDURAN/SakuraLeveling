from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.item_definition import ItemDefinition
from app.infrastructure.db.models.item_model import ItemDefinitionModel


class ItemRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_code(self, code: str) -> ItemDefinition | None:
        stmt = select(ItemDefinitionModel).where(ItemDefinitionModel.code == code)
        model = self.session.execute(stmt).scalar_one_or_none()

        if model is None:
            return None

        return self._to_domain(model)

    def create(
        self,
        code: str,
        name: str,
        description: str,
        category: str,
        rarity: str = "common",
        stackable: bool = True,
        max_stack: int | None = None,
        sell_price: int = 0,
        buy_price: int | None = None,
        icon: str | None = None,
        stat_bonuses: dict | None = None,
    ) -> ItemDefinition:
        model = ItemDefinitionModel(
            code=code,
            name=name,
            description=description,
            category=category,
            rarity=rarity,
            stackable=stackable,
            max_stack=max_stack,
            sell_price=sell_price,
            buy_price=buy_price,
            icon=icon,
            stat_bonuses_json=stat_bonuses,
        )

        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)

        return self._to_domain(model)

    def _to_domain(self, model: ItemDefinitionModel) -> ItemDefinition:
        return ItemDefinition(
            id=model.id,
            code=model.code,
            name=model.name,
            description=model.description,
            category=model.category,
            rarity=model.rarity,
            stackable=model.stackable,
            max_stack=model.max_stack,
            sell_price=model.sell_price,
            buy_price=model.buy_price,
            icon=model.icon,
            stat_bonuses=model.stat_bonuses_json,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )