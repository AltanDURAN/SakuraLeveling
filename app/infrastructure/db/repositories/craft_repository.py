from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities.craft_ingredient import CraftIngredient
from app.domain.entities.craft_recipe import CraftRecipe
from app.infrastructure.db.models.craft_model import CraftRecipeIngredientModel, CraftRecipeModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel


class CraftRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_code(self, code: str) -> CraftRecipe | None:
        stmt = select(CraftRecipeModel).where(CraftRecipeModel.code == code)
        recipe_model = self.session.execute(stmt).scalar_one_or_none()

        if recipe_model is None:
            return None

        return self._to_domain(recipe_model)

    def list_all(self) -> list[CraftRecipe]:
        stmt = select(CraftRecipeModel).order_by(CraftRecipeModel.id.asc())
        models = self.session.execute(stmt).scalars().all()
        return [self._to_domain(model) for model in models]

    def create(
        self,
        code: str,
        name: str,
        result_item_definition_id: int,
        result_quantity: int,
        ingredients: list[tuple[int, int]],
    ) -> CraftRecipe:
        recipe_model = CraftRecipeModel(
            code=code,
            name=name,
            result_item_definition_id=result_item_definition_id,
            result_quantity=result_quantity,
        )

        self.session.add(recipe_model)
        self.session.flush()

        for item_definition_id, quantity in ingredients:
            ingredient_model = CraftRecipeIngredientModel(
                craft_recipe_id=recipe_model.id,
                item_definition_id=item_definition_id,
                quantity=quantity,
            )
            self.session.add(ingredient_model)

        self.session.commit()
        self.session.refresh(recipe_model)

        return self._to_domain(recipe_model)

    def _to_domain(self, recipe_model: CraftRecipeModel) -> CraftRecipe:
        result_item = self.session.get(ItemDefinitionModel, recipe_model.result_item_definition_id)

        ingredient_stmt = select(CraftRecipeIngredientModel).where(
            CraftRecipeIngredientModel.craft_recipe_id == recipe_model.id
        )
        ingredient_models = self.session.execute(ingredient_stmt).scalars().all()

        ingredients: list[CraftIngredient] = []
        for ingredient_model in ingredient_models:
            item_model = self.session.get(ItemDefinitionModel, ingredient_model.item_definition_id)
            if item_model is None:
                continue

            ingredients.append(
                CraftIngredient(
                    item_code=item_model.code,
                    quantity=ingredient_model.quantity,
                )
            )

        return CraftRecipe(
            id=recipe_model.id,
            code=recipe_model.code,
            name=recipe_model.name,
            result_item_code=result_item.code if result_item else "",
            result_quantity=recipe_model.result_quantity,
            ingredients=ingredients,
            created_at=recipe_model.created_at,
            updated_at=recipe_model.updated_at,
        )