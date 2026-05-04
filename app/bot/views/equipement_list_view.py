"""View paginée de la liste des équipements possédés par un joueur.

Pages par sous-catégorie : casques, plastrons, jambières, bottes, armes,
boucliers, colliers, bracelets, bagues, ceintures, capes, boucles d'oreilles.

Chaque ligne montre un item équipable de l'inventaire du joueur, avec
indicateur "✅ équipé" si l'item est actuellement porté (et dans quel slot).

Ne contient PAS la page 'Tout' — on force le tri par catégorie.
"""

from __future__ import annotations

import discord

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.entities.player_inventory_item import PlayerInventoryItem


PAGES: list[tuple[str, str, str]] = [
    # (category, label, emoji)
    ("helmet", "Casques", "🪖"),
    ("chest", "Plastrons", "🦺"),
    ("legs", "Jambières", "👖"),
    ("boots", "Bottes", "🥾"),
    ("weapon", "Armes", "⚔️"),
    ("shield", "Boucliers", "🛡️"),
    ("necklace", "Colliers", "📿"),
    ("bracelet", "Bracelets", "⛓️"),
    ("ring", "Bagues", "💍"),
    ("belt", "Ceintures", "🪢"),
    ("cape", "Capes", "🧥"),
    ("earring", "Boucles d'oreilles", "💎"),
]


def _equipped_item_def_ids(equipped: list[PlayerEquipmentItem]) -> dict[int, str]:
    """Retourne {item_definition_id → slot} pour tous les items équipés."""
    return {e.item_definition.id: e.slot for e in equipped}


def _filter_for_category(
    items: list[PlayerInventoryItem], category: str,
) -> list[PlayerInventoryItem]:
    return [i for i in items if i.item_definition.category == category]


def build_equipement_embed(
    display_name: str,
    items: list[PlayerInventoryItem],
    equipped: list[PlayerEquipmentItem],
    page_key: str,
) -> discord.Embed:
    label, emoji = next(
        ((lbl, emj) for cat, lbl, emj in PAGES if cat == page_key),
        ("Équipement", "🛡️"),
    )

    embed = discord.Embed(
        title=f"🛡️ Équipements de {display_name}",
        color=discord.Color.dark_blue(),
    )

    page_items = _filter_for_category(items, page_key)
    equipped_map = _equipped_item_def_ids(equipped)

    if not page_items:
        body = "_Aucun item dans cette catégorie._"
    else:
        page_items_sorted = sorted(
            page_items, key=lambda i: (-i.quantity, i.item_definition.name),
        )
        lines = []
        for inv_item in page_items_sorted:
            d = inv_item.item_definition
            qty_label = f" ×{inv_item.quantity}" if inv_item.quantity > 1 else ""
            equipped_marker = ""
            if d.id in equipped_map:
                equipped_marker = " · ✅ **équipé**"
            lines.append(
                f"`{d.code}` — **{d.name}**{qty_label}{equipped_marker}"
            )
        body = "\n".join(lines)
        if len(body) > 3900:
            body = body[:3900] + "\n_… (liste tronquée)_"

    embed.description = body
    n = len(page_items)
    item_word = "item" if n <= 1 else "items"
    embed.set_author(name=f"{emoji} {label} ({n} {item_word})")

    nav_parts: list[str] = []
    for cat, lbl, emj in PAGES:
        count = len(_filter_for_category(items, cat))
        marker = "**" if cat == page_key else ""
        nav_parts.append(f"{marker}{emj} {lbl} ({count}){marker}")
    embed.set_footer(
        text=" | ".join(nav_parts[:6]) + " …" if len(nav_parts) > 6 else " | ".join(nav_parts)
    )
    return embed


class _PageButton(discord.ui.Button):
    def __init__(self, page_key: str, label: str, emoji: str, count: int) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=f"{label} ({count})",
            emoji=emoji,
        )
        self.page_key = page_key

    async def callback(self, interaction: discord.Interaction) -> None:
        view: EquipementListView = self.view  # type: ignore[assignment]
        view.current_page = self.page_key
        await interaction.response.edit_message(
            embed=view._build_embed(), view=view,
        )


class EquipementListView(discord.ui.View):
    def __init__(
        self,
        display_name: str,
        items: list[PlayerInventoryItem],
        equipped: list[PlayerEquipmentItem],
        timeout: float = 300.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.display_name = display_name
        self.items = items
        self.equipped = equipped

        # On filtre dès le début sur les catégories équipables possédées
        # pour ne pas afficher trop de boutons vides.
        present_categories = {
            i.item_definition.category for i in items
            if any(c == i.item_definition.category for c, _, _ in PAGES)
        }
        # Page par défaut : la première catégorie présente, ou helmet sinon
        self.current_page = next(
            (c for c, _, _ in PAGES if c in present_categories),
            PAGES[0][0],
        )

        # Limite Discord : 25 components / view, 5 par row → on a 12 catégories
        # → 12 boutons max. Display all categories pour permettre la navigation
        # complète même quand vide (compteur "(0)" indicatif).
        for cat, label, emoji in PAGES:
            count = len(_filter_for_category(items, cat))
            self.add_item(_PageButton(
                page_key=cat, label=label, emoji=emoji, count=count,
            ))

    def _build_embed(self) -> discord.Embed:
        return build_equipement_embed(
            self.display_name, self.items, self.equipped,
            page_key=self.current_page,
        )
