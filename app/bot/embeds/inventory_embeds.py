"""Embeds pour l'inventaire paginé par catégorie.

L'inventaire d'un joueur ne contient que les items NON équipables
(consommables et ressources). Les items équipables (armes, armures,
accessoires) sont gérés séparément via /equipement_list.

Pas de page 'Tout' : on force le tri par catégorie pour la lisibilité.
"""

import discord

from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session

from app.domain.entities.player_inventory_item import PlayerInventoryItem
from app.shared.enums import EQUIPABLE_CATEGORIES


# Pages affichées dans /inventory. Plus d'équipables ici — uniquement
# consommables et ressources. Pas de page 'Tout'.
PAGES: list[tuple[str, str, str]] = [
    # (page_key, label, emoji)
    ("consumable", "Consommables", "🧪"),
    ("resource", "Ressources & drops", "🌾"),
]

# Catégories équipables : filtrées hors de l'inventaire (elles s'affichent
# dans /equipement_liste). Liste canonique dans enums pour éviter la dérive.

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
            "`/equipement_liste`)."
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
            f"{i.item_definition.name} **×{i.quantity}**"
            for i in page_items_sorted
        ]
        body = "\n".join(lines)
        if len(body) > 3900:
            body = body[:3900] + "\n_… (liste tronquée)_"

    embed.description = body
    n = len(page_items_sorted)
    item_word = "item" if n <= 1 else "items"
    embed.set_author(name=f"{page_emoji} {page_label} ({n} {item_word})")

    return embed


def item_names(codes: set[str]) -> dict[str, str]:
    """Le nom affiché de ces objets (code → nom) : un joueur ne doit jamais
    voir un code comme `potion_soin`."""
    if not codes:
        return {}
    with get_db_session() as session:
        repository = ItemRepository(session)
        items = {code: repository.get_by_code(code) for code in codes}
    return {code: item.name for code, item in items.items() if item is not None}
