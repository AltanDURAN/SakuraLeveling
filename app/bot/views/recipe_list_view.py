"""Vue de listes de recettes (/craft_list, /forge_list) avec boutons de
filtre par catégorie d'item (armes, casques, bagues, etc.).

Le bouton 'Tout' montre l'ensemble des recettes de la liste. Cliquer sur
un autre bouton filtre l'embed pour ne montrer que cette catégorie.
Tous les boutons sont accessibles à n'importe quel utilisateur (vue
publique, lecture seule).
"""

from __future__ import annotations

import discord

from app.bot.embeds.craft_embeds import CATEGORY_LABELS, build_craft_list_embed
from app.domain.entities.craft_recipe import CraftRecipe
from app.domain.entities.item_definition import ItemDefinition


# Limite Discord : 25 components par view, 5 par row → on peut placer
# jusqu'à ~25 filtres. En pratique on n'aura jamais plus de 12 catégories.
_MAX_BUTTONS = 24


class _CategoryButton(discord.ui.Button):
    def __init__(
        self,
        category: str | None,
        label: str,
        emoji: str | None,
        style: discord.ButtonStyle,
        count: int,
    ) -> None:
        # `category=None` = bouton "Tout"
        super().__init__(
            label=f"{label} ({count})",
            emoji=emoji,
            style=style,
        )
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        view: RecipeListView = self.view  # type: ignore[assignment]
        view.current_category = self.category
        view._refresh_styles()
        await interaction.response.edit_message(
            embed=view._build_embed(), view=view,
        )


class RecipeListView(discord.ui.View):
    def __init__(
        self,
        recipes: list[CraftRecipe],
        item_lookup: dict[str, ItemDefinition],
        title_prefix: str,
        color: discord.Color,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.recipes = recipes
        self.item_lookup = item_lookup
        self.title_prefix = title_prefix
        self.color = color
        self.current_category: str | None = None  # None = "Tout"

        self._build_buttons()

    def _category_of(self, recipe: CraftRecipe) -> str | None:
        item = self.item_lookup.get(recipe.result_item_code)
        return item.category if item else None

    def _build_buttons(self) -> None:
        # Calcule les compteurs par catégorie
        by_cat: dict[str, int] = {}
        for r in self.recipes:
            cat = self._category_of(r)
            if cat:
                by_cat[cat] = by_cat.get(cat, 0) + 1

        # Bouton "Tout" en premier (style primary par défaut)
        self.add_item(
            _CategoryButton(
                category=None,
                label="Tout",
                emoji="📜",
                style=discord.ButtonStyle.primary,
                count=len(self.recipes),
            )
        )

        # Un bouton par catégorie présente, dans l'ordre du mapping CATEGORY_LABELS
        # (plus joli qu'un dict order arbitraire). Limite à 24 boutons (1 + 23).
        added = 1
        for cat, (label, emoji) in CATEGORY_LABELS.items():
            if cat not in by_cat:
                continue
            if added >= _MAX_BUTTONS:
                break
            self.add_item(
                _CategoryButton(
                    category=cat,
                    label=label,
                    emoji=emoji,
                    style=discord.ButtonStyle.secondary,
                    count=by_cat[cat],
                )
            )
            added += 1

    def _refresh_styles(self) -> None:
        # Bouton actif = primary, autres = secondary
        for child in self.children:
            if isinstance(child, _CategoryButton):
                child.style = (
                    discord.ButtonStyle.primary
                    if child.category == self.current_category
                    else discord.ButtonStyle.secondary
                )

    def _filtered_recipes(self) -> list[CraftRecipe]:
        if self.current_category is None:
            return self.recipes
        return [r for r in self.recipes if self._category_of(r) == self.current_category]

    def _build_embed(self) -> discord.Embed:
        filtered = self._filtered_recipes()
        if self.current_category is None:
            title = f"{self.title_prefix} — Toutes les recettes"
        else:
            label, emoji = CATEGORY_LABELS.get(
                self.current_category, (self.current_category, "📂"),
            )
            title = f"{self.title_prefix} — {emoji} {label}"
        return build_craft_list_embed(
            recipes=filtered,
            item_lookup=self.item_lookup,
            title=title,
            color=self.color,
        )
