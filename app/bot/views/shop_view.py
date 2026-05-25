"""Vue paginée du /shop par catégorie d'item — achat uniquement (V2).

La vente n'existe plus : on ne peut qu'acheter. Les drops de mob ne sont pas
en boutique (ils servent au craft). Présentation soignée : un onglet par
grande catégorie, items avec icône + rareté + description + prix.
"""

from __future__ import annotations

import discord

from app.domain.entities.shop_item import ShopItem
from app.shared.enums import CATEGORY_ICONS
from app.shared.formatters import format_int as _format_int


# Pages : (label bouton, emoji, catégories incluses).
_PAGES: list[tuple[str, str, frozenset[str]]] = [
    ("Armes", "⚔️", frozenset({"weapon"})),
    ("Boucliers", "🛡️", frozenset({"shield"})),
    ("Armure", "🪖", frozenset({"helmet", "chest", "legs", "boots"})),
    ("Accessoires", "💍", frozenset({"necklace", "bracelet", "ring", "belt", "cape", "earring"})),
    ("Consommables", "🧪", frozenset({"consumable"})),
    ("Ressources", "📦", frozenset({"resource"})),
]

# Pastille de rareté (lisibilité visuelle d'un coup d'œil).
_RARITY_DOT: dict[str, str] = {
    "common": "⚪",
    "uncommon": "🟢",
    "rare": "🔵",
    "epic": "🟣",
    "legendary": "🟠",
}


def _build_page_embed(
    page_label: str,
    page_emoji: str,
    items: list[ShopItem],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏪  Boutique",
        description=f"### {page_emoji}  {page_label}",
        color=discord.Color.from_rgb(228, 178, 92),  # or chaud
    )

    if not items:
        embed.description += "\n\n_Aucun article dans cette catégorie pour le moment._"
        return embed

    # Tri : par prix croissant (les articles abordables d'abord).
    items = sorted(items, key=lambda s: s.buy_price)

    for shop_item in items:
        item_def = shop_item.item_definition
        emoji = CATEGORY_ICONS.get(item_def.category, "📦")
        dot = _RARITY_DOT.get(item_def.rarity, "⚪")

        desc = (item_def.description or "").strip()
        if len(desc) > 90:
            desc = desc[:87] + "…"

        value_lines = []
        if desc:
            value_lines.append(f"_{desc}_")
        value_lines.append(
            f"💰 **{_format_int(shop_item.buy_price)}** or   ·   `/buy {item_def.code}`"
        )

        embed.add_field(
            name=f"{emoji}  {item_def.name}  {dot}",
            value="\n".join(value_lines),
            inline=False,
        )

    embed.set_footer(text="🛒  Achetez avec  /buy <objet> <quantité>   ·   La revente n'existe pas.")
    return embed


class _PageButton(discord.ui.Button):
    def __init__(
        self,
        label: str,
        emoji: str,
        category_set: frozenset[str],
        count: int,
        is_active: bool,
    ) -> None:
        super().__init__(
            label=f"{label} ({count})",
            emoji=emoji,
            style=discord.ButtonStyle.primary if is_active else discord.ButtonStyle.secondary,
            disabled=count == 0,
        )
        self.label_text = label
        self.emoji_text = emoji
        self.category_set = category_set

    async def callback(self, interaction: discord.Interaction) -> None:
        view: ShopView = self.view  # type: ignore[assignment]
        view.current_categories = self.category_set
        view.current_page_label = self.label_text
        view.current_page_emoji = self.emoji_text
        view._refresh_styles()
        await interaction.response.edit_message(
            embed=view._build_embed(), view=view,
        )


class ShopView(discord.ui.View):
    """Vue publique (lecture seule) — n'importe qui peut naviguer entre onglets."""

    def __init__(
        self,
        shop_items: list[ShopItem],
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.shop_items = [s for s in shop_items if s.enabled]

        counts: dict[str, int] = {}
        for s in self.shop_items:
            cat = s.item_definition.category
            counts[cat] = counts.get(cat, 0) + 1

        self.current_categories: frozenset[str] = frozenset()
        self.current_page_label = ""
        self.current_page_emoji = ""

        # Seuls les onglets non vides apparaissent.
        for label, emoji, cat_set in _PAGES:
            page_count = sum(counts.get(c, 0) for c in cat_set)
            if page_count == 0:
                continue
            if not self.current_categories:
                self.current_categories = cat_set
                self.current_page_label = label
                self.current_page_emoji = emoji

            self.add_item(
                _PageButton(
                    label=label,
                    emoji=emoji,
                    category_set=cat_set,
                    count=page_count,
                    is_active=(cat_set == self.current_categories),
                )
            )

    def _items_in_current_page(self) -> list[ShopItem]:
        if not self.current_categories:
            return []
        return [
            s for s in self.shop_items
            if s.item_definition.category in self.current_categories
        ]

    def _build_embed(self) -> discord.Embed:
        if not self.shop_items:
            return discord.Embed(
                title="🏪  Boutique",
                description=(
                    "La boutique est vide pour le moment.\n"
                    "Demandez à un admin d'y ajouter des articles."
                ),
                color=discord.Color.from_rgb(228, 178, 92),
            )
        return _build_page_embed(
            self.current_page_label,
            self.current_page_emoji,
            self._items_in_current_page(),
        )

    def _refresh_styles(self) -> None:
        for child in self.children:
            if isinstance(child, _PageButton):
                child.style = (
                    discord.ButtonStyle.primary
                    if child.category_set == self.current_categories
                    else discord.ButtonStyle.secondary
                )
