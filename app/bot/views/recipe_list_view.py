"""Liste paginée des recettes (/craft_list, /forge_list).

Rendu en image Pillow (cohérent avec /equipement, /equipement_list).
Chaque page = une catégorie d'item (armes, casques, bagues, etc) avec
filtre par boutons. Pagination interne ◀ ▶ si > 6 recettes par catégorie.
"""

from __future__ import annotations

import discord

from app.bot.rendering.item_card_grid import (
    CardSpec,
    compose_card_grid_page,
    item_asset_path,
)
from app.domain.entities.craft_recipe import CraftRecipe
from app.domain.entities.item_definition import ItemDefinition
from app.shared.emoji_mappings import format_stat_bonuses_short
from app.shared.enums import CATEGORY_ICONS
from app.shared.paths import GENERATED_LISTS_DIR


# Libellés conviviaux par catégorie (déplacés depuis craft_embeds.py).
CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    "weapon":     ("Armes",              "⚔️"),
    "shield":     ("Boucliers",          "🛡️"),
    "helmet":     ("Casques",            "⛑️"),
    "chest":      ("Plastrons",          "👕"),
    "legs":       ("Jambières",          "👖"),
    "boots":      ("Bottes",             "🥾"),
    "necklace":   ("Colliers",           "📿"),
    "bracelet":   ("Bracelets",          "⛓️"),
    "ring":       ("Bagues",             "💍"),
    "belt":       ("Ceintures",          "🎗️"),
    "cape":       ("Capes",              "🧣"),
    "earring":    ("Boucles d'oreilles", "👂"),
    "consumable": ("Consommables",       "🧪"),
    "resource":   ("Ressources",         "🌾"),
}


_CATEGORY_ACCENT: dict[str, tuple[int, int, int, int]] = {
    "weapon":   (235, 100, 100, 255),
    "shield":   (90, 160, 230, 255),
    "helmet":   (235, 200, 100, 255),
    "chest":    (200, 130, 90, 255),
    "legs":     (130, 110, 90, 255),
    "boots":    (160, 100, 70, 255),
    "necklace": (220, 180, 240, 255),
    "bracelet": (200, 220, 255, 255),
    "ring":     (255, 215, 100, 255),
    "belt":     (180, 160, 130, 255),
    "cape":     (160, 100, 200, 255),
    "earring":  (255, 200, 220, 255),
}


_PAGE_SIZE = 6  # 2 cols × 3 rows : laisse de la place pour les ingrédients
_MAX_BUTTONS = 12


def _format_ingredients(
    recipe: CraftRecipe, item_lookup: dict[str, ItemDefinition],
) -> str:
    parts: list[str] = []
    for ing in recipe.ingredients:
        item = item_lookup.get(ing.item_code)
        name = item.name if item else ing.item_code
        parts.append(f"{ing.quantity}× {name}")
    return " · ".join(parts)


def _build_card(
    recipe: CraftRecipe,
    item_lookup: dict[str, ItemDefinition],
    accent: tuple[int, int, int, int] | None,
) -> CardSpec:
    result = item_lookup.get(recipe.result_item_code)
    name = result.name if result else recipe.result_item_code
    if recipe.result_quantity > 1:
        name = f"×{recipe.result_quantity}  {name}"

    lines: list[str] = []
    if result:
        bonuses_text = format_stat_bonuses_short(result.stat_bonuses)
        if bonuses_text:
            lines.append(bonuses_text)
    lines.append("📦 " + _format_ingredients(recipe, item_lookup))
    lines.append(f"🔖 `{recipe.code}`")

    icon_emoji = CATEGORY_ICONS.get(
        result.category if result else "", "🛠️",
    )
    return CardSpec(
        name=name,
        icon_emoji=icon_emoji,
        icon_path=item_asset_path(result.code) if result else None,
        accent=accent,
        lines=lines,
        code=recipe.code,
    )


class _CategoryButton(discord.ui.Button):
    def __init__(
        self,
        category: str,
        label: str,
        emoji: str,
        count: int,
        is_active: bool,
    ) -> None:
        super().__init__(
            style=(
                discord.ButtonStyle.primary if is_active
                else discord.ButtonStyle.secondary
            ),
            label=f"{label} ({count})",
            emoji=emoji,
        )
        self.category = category

    async def callback(self, interaction: discord.Interaction) -> None:
        view: RecipeListView = self.view  # type: ignore[assignment]
        view.current_category = self.category
        view.page_index = 0
        view._refresh_styles()
        await view._send_update(interaction)


class _PrevPageButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.primary, emoji="⬅️", row=4,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: RecipeListView = self.view  # type: ignore[assignment]
        if view.page_index > 0:
            view.page_index -= 1
        await view._send_update(interaction)


class _NextPageButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.primary, emoji="➡️", row=4,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view: RecipeListView = self.view  # type: ignore[assignment]
        view.page_index += 1
        await view._send_update(interaction)


class RecipeListView(discord.ui.View):
    def __init__(
        self,
        recipes: list[CraftRecipe],
        item_lookup: dict[str, ItemDefinition],
        title_prefix: str,
        color: discord.Color,
        viewer_id: int,
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.recipes = recipes
        self.item_lookup = item_lookup
        self.title_prefix = title_prefix
        self.color = color
        self.viewer_id = viewer_id
        self.page_index = 0
        self.current_category: str | None = None

        # Compteurs par catégorie
        self._by_cat: dict[str, int] = {}
        for r in recipes:
            cat = self._cat_of(r)
            if cat:
                self._by_cat[cat] = self._by_cat.get(cat, 0) + 1

        # Catégorie par défaut : première dans CATEGORY_LABELS qui a des recettes
        for cat in CATEGORY_LABELS.keys():
            if cat in self._by_cat:
                self.current_category = cat
                break

        # Boutons de catégorie
        added = 0
        for cat, (label, emoji) in CATEGORY_LABELS.items():
            if cat not in self._by_cat:
                continue
            if added >= _MAX_BUTTONS:
                break
            self.add_item(_CategoryButton(
                category=cat, label=label, emoji=emoji,
                count=self._by_cat[cat],
                is_active=(cat == self.current_category),
            ))
            added += 1

        # Pagination interne
        self.prev_btn = _PrevPageButton()
        self.next_btn = _NextPageButton()
        self.add_item(self.prev_btn)
        self.add_item(self.next_btn)

    def _cat_of(self, recipe: CraftRecipe) -> str | None:
        item = self.item_lookup.get(recipe.result_item_code)
        return item.category if item else None

    def _filtered(self) -> list[CraftRecipe]:
        if self.current_category is None:
            return list(self.recipes)
        return [r for r in self.recipes if self._cat_of(r) == self.current_category]

    def _refresh_styles(self) -> None:
        for child in self.children:
            if isinstance(child, _CategoryButton):
                child.style = (
                    discord.ButtonStyle.primary
                    if child.category == self.current_category
                    else discord.ButtonStyle.secondary
                )

    def render_current(self) -> tuple[discord.Embed, discord.File]:
        GENERATED_LISTS_DIR.mkdir(parents=True, exist_ok=True)
        all_filtered = self._filtered()
        total = len(all_filtered)
        total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self.page_index = max(0, min(self.page_index, total_pages - 1))

        chunk = all_filtered[
            self.page_index * _PAGE_SIZE:(self.page_index + 1) * _PAGE_SIZE
        ]
        cat = self.current_category or "_"
        accent = _CATEGORY_ACCENT.get(cat)
        cards = [_build_card(r, self.item_lookup, accent) for r in chunk]

        if cat in CATEGORY_LABELS:
            label, emoji = CATEGORY_LABELS[cat]
            sub = f"{emoji} {label} ({total})"
        else:
            sub = f"📂 {total} recette(s)"
        if total_pages > 1:
            sub += f"  —  page {self.page_index + 1}/{total_pages}"

        # Nom de fichier basé sur viewer + catégorie + page (overwrites volontaires)
        out = (
            GENERATED_LISTS_DIR
            / f"recipes_{self.viewer_id}_{cat}_p{self.page_index + 1}.png"
        )
        compose_card_grid_page(
            str(out), title=self.title_prefix, subtitle=sub,
            cards=cards, cols=2, rows=3, seed=self.viewer_id,
        )

        # Désactive les flèches si pas de pagination interne
        self.prev_btn.disabled = self.page_index == 0
        self.next_btn.disabled = self.page_index >= total_pages - 1

        filename = str(out).rsplit("/", 1)[-1]
        embed = discord.Embed(color=self.color)
        embed.set_image(url=f"attachment://{filename}")
        file = discord.File(str(out), filename=filename)
        return embed, file

    async def _send_update(self, interaction: discord.Interaction) -> None:
        embed, file = self.render_current()
        await interaction.response.edit_message(
            embed=embed, attachments=[file], view=self,
        )
