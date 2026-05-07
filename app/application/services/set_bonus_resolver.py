"""Helper centralisé pour calculer les bonus de panoplie d'un joueur.

Évite que chaque caller de StatsService ait à charger les définitions
de sets + instancier le service. Pattern identique à
`title_bonus_resolver.resolve_title_bonuses`.
"""

from __future__ import annotations

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.domain.services.set_bonus_service import SetBonuses, SetBonusService
from app.infrastructure.sets.set_loader import list_definitions as _list_set_defs


def resolve_set_bonuses(
    equipped_items: list[PlayerEquipmentItem],
) -> SetBonuses:
    """Renvoie l'agrégation des bonus de panoplies à partir des items
    actuellement équipés."""
    return SetBonusService(_list_set_defs()).aggregate(equipped_items)
