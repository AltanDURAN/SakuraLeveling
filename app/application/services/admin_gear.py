"""Donner / retirer des pièces d'équipement depuis les outils d'administration.

Équipement v2 : une pièce n'est JAMAIS dans l'inventaire (`player_gear`, une
ligne par exemplaire). Les outils admin qui donnent un « objet » doivent donc
aiguiller l'équipement ici — sinon la pièce finissait dans l'inventaire,
invisible et inutilisable. Partagé par la commande `/admin give_item` et
l'admin web (actions rapides, fiche joueur).
"""

from __future__ import annotations

from app.domain.services.gear_service import rarity_index
from app.infrastructure.db.repositories.gear_repository import GearRepository
from app.shared.enums import EQUIPABLE_CATEGORIES
from app.infrastructure.db.unit_of_work import commit

#: Garde-fou : c'est un outil de test, pas une usine.
MAX_COPIES_PER_GIFT = 20


def is_gear(item) -> bool:
    return getattr(item, "category", None) in EQUIPABLE_CATEGORIES


def give_gear(session, player_id: int, item, quantity: int,
              rarity: str = "common", forge_level: int = 0) -> int:
    """Crée `quantity` copies (plafonnées) ; renvoie le nombre créé."""
    repo = GearRepository(session)
    quantity = max(0, min(quantity, MAX_COPIES_PER_GIFT))
    for _ in range(quantity):
        repo.add(player_id, item.id, rarity, forge_level, source="admin", commit=False)
    commit(session)
    return quantity


def take_gear(session, player_id: int, item, quantity: int) -> int:
    """Retire jusqu'à `quantity` copies, les moins précieuses d'abord, les
    portées en dernier ; une copie en vente n'est jamais touchée. Renvoie le
    nombre retiré."""
    repo = GearRepository(session)
    copies = sorted(
        (g for g in repo.list_owned(player_id) if g.item_definition.id == item.id),
        key=lambda g: (g.equipped, rarity_index(g.rarity), g.forge_level),
    )[:max(0, quantity)]
    for g in copies:
        repo.remove(g.id, commit=False)
    commit(session)
    return len(copies)
