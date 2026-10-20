"""LE joueur de référence — définition unique, partagée par tous les calibrages.

Les monstres, les boss, les gardiens d'épreuve et le prix des artisans sont
tous calibrés « relativement à un joueur de ce niveau ». Chaque script avait sa
propre idée de ce qu'était ce joueur, et ces idées avaient divergé. Une seule
définition désormais : si elle change, tout se recalibre de façon cohérente.

Hypothèses, volontairement neutres :

  • **répartition équilibrée** — le joueur a `niveau - 1` points de stats et en
    place un tiers dans chacune des trois stats de base. C'est la seule
    hypothèse qui ne favorise aucun build ;
  • **équipement de son palier** — il porte des pièces correspondant à son
    niveau, soit `EXPECTED_GEAR_PERCENT` de bonus sur les stats structurelles.
    Calibrer sur un joueur nu rendrait tout le contenu trivial dès qu'il
    s'équipe ; calibrer sur un joueur parfaitement optimisé le rendrait
    infranchissable pour tous les autres ;
  • **sauf au tout début** — un nouveau joueur n'a RIEN sur le dos. Le bonus
    attendu monte donc de 0 % au niveau 1 à `EXPECTED_GEAR_PERCENT` au niveau
    `GEAR_RAMP_END_LEVEL` (`expected_gear_percent`). Avant cette rampe, tout
    était calibré sur +50 % dès le niveau 1 : un compte neuf perdait 100 % de
    ses combats, même contre un slime (audit d'octobre 2026).
"""

from __future__ import annotations

from app.domain.value_objects.base_stats import (
    ATTACK_PER_POINT,
    DEFENSE_PER_POINT,
    MAX_HP_PER_POINT,
    START_ATTACK,
    START_DEFENSE,
    START_MAX_HP,
)
from app.domain.value_objects.stats import Stats

#: Bonus structurel qu'on suppose à un joueur correctement équipé pour son
#: palier (équipement + plus tard l'arbre). +50 % = « bien équipé sans être
#: optimisé ».
EXPECTED_GEAR_PERCENT = 0.50

#: Niveau où le joueur de référence atteint l'équipement « de son palier ».
GEAR_RAMP_END_LEVEL = 15


def expected_gear_percent(level: int) -> float:
    """Bonus d'équipement attendu à ce niveau : 0 au niveau 1, plafond au
    niveau `GEAR_RAMP_END_LEVEL` (rampe linéaire)."""
    progress = max(0, level - 1) / max(1, GEAR_RAMP_END_LEVEL - 1)
    return EXPECTED_GEAR_PERCENT * min(1.0, progress)

#: Valeurs de départ des stats secondaires (miroir de StatsService).
BASE_SPEED = 5
BASE_CRIT_CHANCE = 5.0
BASE_CRIT_DAMAGE = 150.0
BASE_DODGE = 0.0
BASE_HP_REGENERATION = 5
BASE_MANA_MAX = 100
BASE_MANA_REGENERATION = 5


def base_points_at(level: int) -> float:
    """Points de stats investis dans CHAQUE stat, en répartition équilibrée."""
    return max(0, level - 1) / 3.0


def reference_stats(
    level: int,
    gear_percent: float | None = None,
    *,
    crit_chance: float | None = None,
    dodge: float | None = None,
) -> Stats:
    """Stats complètes du joueur de référence à ce niveau."""
    points = base_points_at(level)
    if gear_percent is None:
        gear_percent = expected_gear_percent(level)
    factor = 1 + max(-0.9, gear_percent)
    return Stats(
        max_hp=max(1, int((START_MAX_HP + MAX_HP_PER_POINT * points) * factor)),
        attack=max(1, int((START_ATTACK + ATTACK_PER_POINT * points) * factor)),
        defense=max(1, int((START_DEFENSE + DEFENSE_PER_POINT * points) * factor)),
        speed=BASE_SPEED,
        crit_chance=BASE_CRIT_CHANCE if crit_chance is None else crit_chance,
        crit_damage=BASE_CRIT_DAMAGE,
        dodge=BASE_DODGE if dodge is None else dodge,
        hp_regeneration=BASE_HP_REGENERATION,
        mana_max=BASE_MANA_MAX,
        mana_regeneration=BASE_MANA_REGENERATION,
    )
