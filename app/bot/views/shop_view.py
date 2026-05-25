"""Vue du /shop par catégorie — rendu en CARTES (image Pillow, même style que
/equipement). Achat uniquement (pas de vente). Onglets par catégorie ; chaque
onglet re-rend l'image de la catégorie.
"""

from __future__ import annotations

import io
import uuid

import discord

from app.bot.rendering.shop_image import compose_shop_page
from app.domain.entities.shop_item import ShopItem


# Pages : (label bouton, emoji, catégories incluses).
_PAGES: list[tuple[str, str, frozenset[str]]] = [
    ("Armes", "⚔️", frozenset({"weapon"})),
    ("Boucliers", "🛡️", frozenset({"shield"})),
    ("Armure", "🪖", frozenset({"helmet", "chest", "legs", "boots"})),
    ("Accessoires", "💍", frozenset({"necklace", "bracelet", "ring", "belt", "cape", "earring"})),
    ("Consommables", "🧪", frozenset({"consumable"})),
    ("Ressources", "📦", frozenset({"resource"})),
]


class _PageButton(discord.ui.Button):
    def __init__(self, label, emoji, category_set, count, is_active):
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
        embed, file = view.render_current()
        await interaction.response.edit_message(embed=embed, attachments=[file], view=view)


class ShopView(discord.ui.View):
    """Vue publique : n'importe qui peut naviguer entre les onglets."""

    def __init__(self, shop_items: list[ShopItem], timeout: float = 300.0) -> None:
        super().__init__(timeout=timeout)
        self.shop_items = [s for s in shop_items if s.enabled]

        counts: dict[str, int] = {}
        for s in self.shop_items:
            counts[s.item_definition.category] = counts.get(s.item_definition.category, 0) + 1

        self.current_categories: frozenset[str] = frozenset()
        self.current_page_label = ""
        self.current_page_emoji = ""

        for label, emoji, cat_set in _PAGES:
            page_count = sum(counts.get(c, 0) for c in cat_set)
            if page_count == 0:
                continue
            if not self.current_categories:
                self.current_categories = cat_set
                self.current_page_label = label
                self.current_page_emoji = emoji
            self.add_item(_PageButton(
                label, emoji, cat_set, page_count,
                is_active=(cat_set == self.current_categories),
            ))

    def _items_in_current_page(self) -> list[ShopItem]:
        if not self.current_categories:
            return []
        return [s for s in self.shop_items if s.item_definition.category in self.current_categories]

    def render_current(self) -> tuple[discord.Embed, discord.File]:
        """Rend l'image de la catégorie courante (PNG en mémoire) + embed."""
        if not self.shop_items:
            embed = discord.Embed(
                title="🏪 Boutique",
                description="La boutique est vide. Demandez à un admin d'ajouter des articles.",
                color=discord.Color.from_rgb(228, 178, 92),
            )
            # Pas d'image → on renvoie un fichier transparent minimal évité :
            # on signale au caller via un embed sans image. Mais l'API edit
            # exige un file si on en avait un ; on gère le cas vide en amont.
            png = compose_shop_page("Boutique", "🏪", [], seed=1)
        else:
            png = compose_shop_page(
                self.current_page_label,
                self.current_page_emoji,
                self._items_in_current_page(),
                seed=hash(self.current_page_label) & 0xFFFF,
            )
            embed = discord.Embed(color=discord.Color.from_rgb(228, 178, 92))

        fname = f"shop_{uuid.uuid4().hex[:8]}.png"
        file = discord.File(io.BytesIO(png), filename=fname)
        embed.set_image(url=f"attachment://{fname}")
        return embed, file

    def _refresh_styles(self) -> None:
        for child in self.children:
            if isinstance(child, _PageButton):
                child.style = (
                    discord.ButtonStyle.primary
                    if child.category_set == self.current_categories
                    else discord.ButtonStyle.secondary
                )
