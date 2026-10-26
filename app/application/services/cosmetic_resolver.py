"""Cosmétiques d'un joueur : ce qu'il POSSÈDE (objets `cosmetic` de son
inventaire, achetés chez Sorn) et ce qu'il PORTE sur sa bannière /profil
(`player_cosmetics`, choisi avec /apparence). Un cosmétique porté mais plus
possédé (échangé, vendu) n'est plus affiché."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_cosmetic_repository import (
    COSMETIC_SLOTS,
    PlayerCosmeticRepository,
)

COSMETIC_CATEGORY = "cosmetic"
SLOT_LABELS: dict[str, str] = {"fond": "🖼️ Fond", "cadre": "⭕ Cadre", "titre": "🏷️ Couleur du titre"}


def cosmetic_slot(item) -> str | None:
    slot = (item.stat_bonuses or {}).get("cosmetic")
    return slot if slot in COSMETIC_SLOTS else None


def owned_cosmetics(session: Session, player_id: int) -> dict[str, list]:
    """{emplacement: [définitions d'objets possédés]}."""
    out: dict[str, list] = {slot: [] for slot in COSMETIC_SLOTS}
    for entry in InventoryRepository(session).list_by_player_id(player_id):
        item = entry.item_definition
        if item.category == COSMETIC_CATEGORY and entry.quantity > 0 and cosmetic_slot(item):
            out[cosmetic_slot(item)].append(item)
    return out


def worn_cosmetics(session: Session, player_id: int) -> dict[str, dict]:
    """{emplacement: apparence} à passer à `compose_profile_banner(cosmetics=)`."""
    worn = PlayerCosmeticRepository(session).get(player_id)
    if not worn:
        return {}
    owned = {item.code: item for items in owned_cosmetics(session, player_id).values() for item in items}
    return {slot: dict(owned[code].stat_bonuses) for slot, code in worn.items()
            if code in owned and cosmetic_slot(owned[code]) == slot}
