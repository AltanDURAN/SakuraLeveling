"""Multiplicateurs élémentaires d'un joueur contre un ennemi d'un élément donné.

L'élément d'attaque est choisi tout seul (`ElementalInfusionService`) : celui
qui frappe le plus fort CETTE cible, compte tenu de sa faiblesse et de la
maîtrise du joueur (Mage compris). Dans l'autre sens, l'élément de l'ennemi
contre les affinités du joueur. Partagé par les combats de zone (un ennemi
ou une meute) et la tour.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.services import element_service
from app.domain.services.combat_passives import CombatPassives, outgoing_elemental_multiplier
from app.domain.services.elemental_infusion_service import ElementalInfusionService
from app.infrastructure.db.repositories.element_affinity_repository import (
    ElementAffinityRepository,
)


def elemental_multipliers(
    session: Session,
    player_ids: list[int],
    mob_element: str,
    passives_by_player: dict[int, CombatPassives] | None = None,
) -> tuple[dict[int, float], dict[int, float]]:
    """({joueur: multiplicateur de ses dégâts}, {joueur: multiplicateur des
    dégâts reçus}) contre un ennemi d'élément `mob_element` (vides s'il est
    neutre)."""
    mob_element = (mob_element or "").strip()
    if not mob_element:
        return {}, {}
    mob_aff = element_service.single_element_affinities(mob_element)
    repo = ElementAffinityRepository(session)
    outgoing: dict[int, float] = {}
    incoming: dict[int, float] = {}
    for player_id in player_ids:
        aff = repo.get_affinities(player_id)
        infusion = ElementalInfusionService().best_for(aff, mob_aff, repo.dead_elements(player_id))
        if infusion.element:
            outgoing[player_id] = outgoing_elemental_multiplier(
                infusion.multiplier, infusion.element, aff, (passives_by_player or {}).get(player_id),
            )
        incoming[player_id] = element_service.damage_multiplier(mob_element, mob_aff, aff)
    return outgoing, incoming
