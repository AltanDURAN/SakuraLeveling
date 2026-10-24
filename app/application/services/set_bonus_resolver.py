"""Helper centralisé pour calculer les bonus de panoplie d'un joueur.

Pattern identique à `title_bonus_resolver.resolve_title_bonuses`. Le type de
bonus est celui choisi par le joueur (`Player.panoplie_bonus`).
"""

from __future__ import annotations

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.services.set_bonus_service import SetBonuses, SetBonusService


def resolve_set_bonuses(
    equipped_items: list[PlayerEquipmentItem],
    bonus_type: str | None = None,
) -> SetBonuses:
    """Bonus de panoplie des pièces portées, dans le type choisi."""
    return SetBonusService().aggregate(equipped_items, bonus_type)
