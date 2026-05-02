import discord

from app.domain.entities.craft_recipe import CraftRecipe
from app.domain.entities.item_definition import ItemDefinition


# Catégories d'items considérées comme des armes (filtrage /forge)
WEAPON_CATEGORIES = {"weapon", "shield"}


def _format_ingredients(recipe: CraftRecipe, item_lookup: dict[str, ItemDefinition]) -> str:
    parts: list[str] = []
    for ingredient in recipe.ingredients:
        item = item_lookup.get(ingredient.item_code)
        name = item.name if item else ingredient.item_code
        parts.append(f"{ingredient.quantity}× {name}")
    return " · ".join(parts)


def _format_stat_bonuses(stat_bonuses: dict | None) -> str:
    if not stat_bonuses:
        return ""
    short = {
        "max_hp": "PV",
        "attack": "atk",
        "defense": "def",
        "speed": "vit",
        "crit_chance": "crit",
        "crit_damage": "dmg crit",
        "dodge": "esq",
        "hp_regeneration": "regen",
    }
    parts = [f"+{v} {short.get(k, k)}" for k, v in stat_bonuses.items() if v]
    return " · ".join(parts)


def _format_recipe_line(
    recipe: CraftRecipe,
    item_lookup: dict[str, ItemDefinition],
) -> str:
    result = item_lookup.get(recipe.result_item_code)
    result_name = result.name if result else recipe.result_item_code
    qty_suffix = f" ×{recipe.result_quantity}" if recipe.result_quantity > 1 else ""

    ingredients_text = _format_ingredients(recipe, item_lookup)

    bonuses_text = _format_stat_bonuses(result.stat_bonuses) if result else ""
    slot_text = ""
    if result and result.equipment_slot:
        slot_label = result.equipment_slot
        if result.requires_two_hands:
            slot_label += " (2 mains)"
        slot_text = f" — _{slot_label}_"

    suffix = f"\n   ↳ {bonuses_text}" if bonuses_text else ""

    return (
        f"🔨 **{result_name}**{qty_suffix}{slot_text}\n"
        f"   `{recipe.code}` · {ingredients_text}{suffix}"
    )


def build_craft_list_embed(
    recipes: list[CraftRecipe],
    item_lookup: dict[str, ItemDefinition] | None = None,
    title: str = "🛠️ Recettes disponibles",
    color: discord.Color | None = None,
) -> discord.Embed:
    item_lookup = item_lookup or {}
    embed = discord.Embed(
        title=title,
        color=color or discord.Color.orange(),
    )

    if not recipes:
        embed.description = "Aucune recette disponible."
        return embed

    lines = [_format_recipe_line(r, item_lookup) for r in recipes]
    embed.description = "\n\n".join(lines)
    embed.set_footer(
        text=f"{len(recipes)} recette(s) — utilisez /craft <code> ou /forge <code> pour fabriquer"
    )
    return embed
