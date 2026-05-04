"""Embeds pour l'inventaire paginé par catégorie.

L'inventaire d'un joueur ne contient que les items NON équipables
(consommables et ressources). Les items équipables (armes, armures,
accessoires) sont gérés séparément via /equipement_list.

Pas de page 'Tout' : on force le tri par catégorie pour la lisibilité.
"""

import discord

from app.domain.entities.player_inventory_item import PlayerInventoryItem


# Pages affichées dans /inventory. Plus d'équipables ici — uniquement
# consommables et ressources. Pas de page 'Tout'.
PAGES: list[tuple[str, str, str]] = [
    # (page_key, label, emoji)
    ("consumable", "Consommables", "🧪"),
    ("resource", "Ressources & drops", "🌾"),
]

# Catégories considérées comme des items équipables (filtrées hors de
# l'inventaire — affichées dans /equipement_list).
EQUIPABLE_CATEGORIES = {
    "weapon", "shield",
    "helmet", "chest", "legs", "boots",
    "necklace", "bracelet", "ring", "belt", "cape", "earring",
}

# Mapping category → page_key pour les items NON équipables uniquement.
_CATEGORY_TO_PAGE: dict[str, str] = {
    "consumable": "consumable",
    "resource": "resource",
}


def _page_for_category(category: str) -> str:
    return _CATEGORY_TO_PAGE.get(category, "resource")


def _is_inventory_item(item: PlayerInventoryItem) -> bool:
    """Filtre : ne garde que les items NON équipables."""
    return item.item_definition.category not in EQUIPABLE_CATEGORIES


def _filter_items_for_page(
    items: list[PlayerInventoryItem], page_key: str
) -> list[PlayerInventoryItem]:
    return [
        i for i in items
        if _is_inventory_item(i)
        and _page_for_category(i.item_definition.category) == page_key
    ]


def build_inventory_embed(
    display_name: str,
    items: list[PlayerInventoryItem],
    page_key: str = "consumable",
) -> discord.Embed:
    page_label, page_emoji = next(
        ((label, emoji) for key, label, emoji in PAGES if key == page_key),
        ("Inventaire", "🎒"),
    )

    embed = discord.Embed(
        title=f"🎒 Inventaire de {display_name}",
        color=discord.Color.green(),
    )
    # Filtre global : on ne garde que les items non équipables. Les armes,
    # armures, accessoires sont visibles via /equipement_list.
    inventory_items = [i for i in items if _is_inventory_item(i)]

    if not inventory_items:
        embed.description = (
            "_Inventaire vide_ (les équipements sont visibles via "
            "`/equipement_list`)."
        )
        return embed

    page_items_sorted = sorted(
        _filter_items_for_page(items, page_key),
        key=lambda i: (-i.quantity, i.item_definition.name),
    )

    if not page_items_sorted:
        body = "_Aucun item dans cette catégorie._"
    else:
        lines = [
            f"`{i.item_definition.code}` — {i.item_definition.name} **×{i.quantity}**"
            for i in page_items_sorted
        ]
        body = "\n".join(lines)
        if len(body) > 3900:
            body = body[:3900] + "\n_… (liste tronquée)_"

    embed.description = body
    n = len(page_items_sorted)
    item_word = "item" if n <= 1 else "items"
    embed.set_author(name=f"{page_emoji} {page_label} ({n} {item_word})")

    nav_parts: list[str] = []
    for key, label, emoji in PAGES:
        count = len(_filter_items_for_page(items, key))
        marker = "**" if key == page_key else ""
        nav_parts.append(f"{marker}{emoji} {label} ({count}){marker}")
    if nav_parts:
        embed.set_footer(text=" | ".join(nav_parts) + " · Équipements via /equipement_list")
    return embed
