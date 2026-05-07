"""Calcule les bonus de panoplie (set bonus) à partir des items équipés.

Une panoplie est un ensemble d'items partageant la même `family`
(ex : "iron", "slime"). Plus un joueur équipe d'items de la même
panoplie, plus le bonus est élevé.

Le `tiers` est une liste ordonnée : on prend le PLUS HAUT palier dont
`min_pieces` est ≤ au nombre d'items équipés. Pas d'addition de paliers
("progressif" = un palier remplace le précédent, pas qu'il s'ajoute).

Exemple — panoplie "iron" avec tiers à 2/4/8/12 et bonus +1/+2/+5/+8 def :
    - 1 item équipé  → aucun bonus
    - 3 items        → +1 def (palier 2)
    - 7 items        → +2 def (palier 4)
    - 10 items       → +5 def (palier 8)
    - 12 items       → +8 def (palier 12)

Quand le joueur déséquipe et tombe sous un palier, le bonus s'estompe
automatiquement au calcul suivant — rien à persister, c'est dérivé.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.entities.player_equipment_item import PlayerEquipmentItem


@dataclass
class ActiveSetBonus:
    """Détail d'une panoplie active (utile pour l'affichage)."""

    family: str
    family_name: str  # "Acier"
    family_icon: str  # "🛡️"
    pieces_equipped: int
    next_tier_pieces: int | None  # combien manque pour le prochain palier
    active_bonus_type: str | None  # "defense_flat", etc. — None si < palier 1
    active_bonus_value: int


@dataclass
class SetBonuses:
    """Agrégation des bonus de toutes les panoplies actives."""

    defense_flat: int = 0
    dodge_flat: int = 0
    crit_chance_flat: int = 0
    crit_damage_flat: int = 0
    hp_regeneration_flat: int = 0
    attack_flat: int = 0
    speed_flat: int = 0
    max_hp_flat: int = 0
    # Détail par panoplie pour affichage dans /equipement page 3
    active_sets: list[ActiveSetBonus] = field(default_factory=list)


class SetBonusService:
    """Compute set bonuses from equipped items + JSON definitions."""

    _SUPPORTED_TYPES = (
        "defense_flat", "dodge_flat", "crit_chance_flat", "crit_damage_flat",
        "hp_regeneration_flat", "attack_flat", "speed_flat", "max_hp_flat",
    )

    def __init__(self, sets_definitions: dict[str, dict]) -> None:
        self.sets_definitions = sets_definitions

    def aggregate(
        self, equipped_items: list[PlayerEquipmentItem],
    ) -> SetBonuses:
        # Compte le nombre d'items par famille (chaque item compte 1)
        counts: dict[str, int] = {}
        for item in equipped_items:
            family = (item.item_definition.family or "").strip()
            if not family:
                continue
            counts[family] = counts.get(family, 0) + 1

        bonuses = SetBonuses()

        for family, count in counts.items():
            set_def = self.sets_definitions.get(family)
            if set_def is None:
                continue  # famille définie sur l'item mais pas dans sets.json

            tiers = sorted(
                set_def.get("tiers", []),
                key=lambda t: int(t.get("min_pieces", 0)),
            )
            if not tiers:
                continue

            # Palier le plus haut atteint (None si pas de palier 1 atteint)
            active_tier = None
            next_tier_pieces = None
            for tier in tiers:
                if count >= int(tier["min_pieces"]):
                    active_tier = tier
                else:
                    next_tier_pieces = int(tier["min_pieces"])
                    break

            active_type = None
            active_value = 0
            if active_tier is not None:
                t_type = active_tier.get("type")
                t_value = int(active_tier.get("value", 0))
                if t_type in self._SUPPORTED_TYPES and t_value > 0:
                    setattr(
                        bonuses, t_type,
                        getattr(bonuses, t_type) + t_value,
                    )
                    active_type = t_type
                    active_value = t_value

            bonuses.active_sets.append(
                ActiveSetBonus(
                    family=family,
                    family_name=set_def.get("name", family),
                    family_icon=set_def.get("icon", "✨"),
                    pieces_equipped=count,
                    next_tier_pieces=next_tier_pieces,
                    active_bonus_type=active_type,
                    active_bonus_value=active_value,
                )
            )

        # Tri stable : panoplies actives (pieces ≥ 2) d'abord, puis par
        # nombre de pièces décroissant. Pratique pour l'affichage.
        bonuses.active_sets.sort(
            key=lambda s: (-(1 if s.active_bonus_type else 0), -s.pieces_equipped),
        )

        return bonuses
