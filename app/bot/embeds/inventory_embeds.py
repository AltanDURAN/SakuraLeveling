"""Embeds pour l'inventaire paginé par catégorie.

L'inventaire d'un joueur peut contenir des dizaines d'items mélangés
(armes, armures, ressources, consommables...). On regroupe tout par
catégorie sur des pages distinctes navigables — un seul écran à la
fois pour une meilleure lisibilité.
"""

import discord

from app.domain.entities.player_inventory_item import PlayerInventoryItem


# Ordre des pages (catégorie → label visible). Une page "🎒 Tout" en
# dernier permet de voir l'inventaire complet d'un coup si besoin.
PAGES: list[tuple[str, str, str]] = [
    # (page_key, label, emoji)
    ("weapon", "Armes & boucliers", "⚔️"),
    ("equipment", "Équipement", "🛡️"),
    ("accessory", "Accessoires", "💎"),
    ("consumable", "Consommables", "🧪"),
    ("resource", "Ressources & drops", "🌾"),
    ("all", "Tout l'inventaire", "🎒"),
]

# Mapping category → page_key. Toute catégorie inconnue tombe dans "resource".
_CATEGORY_TO_PAGE: dict[str, str] = {
    "weapon": "weapon",
    "shield": "weapon",
    "helmet": "equipment",
    "chest": "equipment",
    "legs": "equipment",
    "boots": "equipment",
    "necklace": "accessory",
    "bracelet": "accessory",
    "ring": "accessory",
    "belt": "accessory",
    "cape": "accessory",
    "earring": "accessory",
    "consumable": "consumable",
    "resource": "resource",
}


def _page_for_category(category: str) -> str:
    return _CATEGORY_TO_PAGE.get(category, "resource")


def _filter_items_for_page(
    items: list[PlayerInventoryItem], page_key: str
) -> list[PlayerInventoryItem]:
    if page_key == "all":
        return items
    return [
        i for i in items if _page_for_category(i.item_definition.category) == page_key
    ]


def build_inventory_embed(
    display_name: str,
    items: list[PlayerInventoryItem],
    page_key: str = "weapon",
) -> discord.Embed:
    page_label, page_emoji = next(
        ((label, emoji) for key, label, emoji in PAGES if key == page_key),
        ("Tout l'inventaire", "🎒"),
    )

    embed = discord.Embed(
        title=f"🎒 Inventaire de {display_name}",
        color=discord.Color.green(),
    )

    if not items:
        embed.description = "Votre inventaire est vide."
        embed.set_footer(text="Aucune page à afficher")
        return embed

    page_items = _filter_items_for_page(items, page_key)
    page_items_sorted = sorted(
        page_items, key=lambda i: (-i.quantity, i.item_definition.name)
    )

    if not page_items_sorted:
        body = "_Aucun item dans cette catégorie._"
    else:
        lines = [
            f"`{i.item_definition.code}` — {i.item_definition.name} **×{i.quantity}**"
            for i in page_items_sorted
        ]
        # Discord cap : 4096 chars dans description. Si dépassement, on tronque.
        body = "\n".join(lines)
        if len(body) > 3900:
            body = body[:3900] + "\n_… (liste tronquée)_"

    embed.description = body
    embed.set_author(name=f"{page_emoji} {page_label} ({len(page_items_sorted)} item(s))")

    # Pagination : indique les pages disponibles avec leur nb d'items
    nav_parts: list[str] = []
    for key, label, emoji in PAGES:
        count = (
            len(items)
            if key == "all"
            else len(_filter_items_for_page(items, key))
        )
        if count == 0 and key != "all":
            continue
        marker = "**" if key == page_key else ""
        nav_parts.append(f"{marker}{emoji} {label} ({count}){marker}")
    if nav_parts:
        embed.set_footer(text=" | ".join(nav_parts))
    return embed
