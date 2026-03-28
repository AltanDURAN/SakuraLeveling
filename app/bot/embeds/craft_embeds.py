import discord

from app.domain.entities.craft_recipe import CraftRecipe


def build_craft_list_embed(recipes: list[CraftRecipe]) -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Recettes disponibles",
        color=discord.Color.orange(),
    )

    if not recipes:
        embed.description = "Aucune recette disponible."
        return embed

    lines = []
    for recipe in recipes:
        ingredients = ", ".join(
            f"{ingredient.item_code} x{ingredient.quantity}"
            for ingredient in recipe.ingredients
        )
        lines.append(
            f"**{recipe.code}** → {recipe.result_item_code} x{recipe.result_quantity}\n"
            f"Ingrédients : {ingredients}"
        )

    embed.description = "\n\n".join(lines)
    return embed