"""Vue paginée du /shop par catégorie d'item.

Plus de wall-of-text : un bouton par grande catégorie (Armes, Armure,
Accessoires, Consommables, Ressources). On ouvre par défaut sur la
première catégorie qui contient au moins un article. Pas de bouton "Tout"
(retiré pour rester cohérent avec /craft_list / /forge_list / /inventory).
"""

from __future__ import annotations

import discord

from app.shared.formatters import format_int as _format_int
from app.domain.entities.shop_item import ShopItem
from app.domain.services.shop_pricing_service import ShopPricingService


# Définition des pages : (label affiché sur le bouton, emoji, set de
# catégories d'item incluses dans la page).
_PAGES: list[tuple[str, str, frozenset[str]]] = [
    ("Armes", "⚔️", frozenset({"weapon"})),
    ("Boucliers", "🛡️", frozenset({"shield"})),
    ("Armure", "🪖", frozenset({"helmet", "chest", "legs", "boots"})),
    ("Accessoires", "💍", frozenset({"necklace", "bracelet", "ring", "belt", "cape", "earring"})),
    ("Consommables", "🧪", frozenset({"consumable"})),
    ("Ressources", "📦", frozenset({"resource"})),
]


def _build_page_embed(
    page_label: str,
    page_emoji: str,
    items: list[ShopItem],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏪 Boutique — {page_emoji} {page_label}",
        color=discord.Color.gold(),
    )

    if not items:
        embed.description = "_Aucun article dans cette catégorie._"
        return embed

    pricing_service = ShopPricingService()
    for shop_item in items:
        item_def = shop_item.item_definition
        current_sell = pricing_service.current_sell_price(shop_item)

        if shop_item.stock_threshold > 0:
            saturation = min(
                100, round(100 * shop_item.current_stock / shop_item.stock_threshold)
            )
        else:
            saturation = 0

        sell_range = (
            f"{shop_item.min_sell_price}–{shop_item.max_sell_price}"
            if shop_item.max_sell_price != shop_item.min_sell_price
            else f"{shop_item.max_sell_price}"
        )

        lines = [
            f"💰 Achat : **{_format_int(shop_item.buy_price)}** or / unité",
            f"💵 Vente : **{_format_int(current_sell)}** or / unité (plage {sell_range})",
            f"📦 Stock : **{shop_item.current_stock}** ({saturation}% saturé)",
        ]

        embed.add_field(
            name=f"📦 {item_def.name} (`{item_def.code}`)",
            value="\n".join(lines),
            inline=False,
        )

    embed.set_footer(
        text="Utilisez /buy <item> <qté> ou /sell <item> <qté>."
    )
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
    """Vue publique (lecture seule) — n'importe qui peut naviguer."""

    def __init__(
        self,
        shop_items: list[ShopItem],
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.shop_items = [s for s in shop_items if s.enabled]

        # Page courante = première catégorie non-vide
        counts: dict[str, int] = {}
        for s in self.shop_items:
            cat = s.item_definition.category
            counts[cat] = counts.get(cat, 0) + 1

        self.current_categories: frozenset[str] = frozenset()
        self.current_page_label = ""
        self.current_page_emoji = ""

        for label, emoji, cat_set in _PAGES:
            page_count = sum(counts.get(c, 0) for c in cat_set)
            if page_count > 0 and not self.current_categories:
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
                title="🏪 Boutique",
                description=(
                    "La boutique est vide pour le moment. "
                    "Demandez à un admin d'y ajouter des articles."
                ),
                color=discord.Color.gold(),
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
