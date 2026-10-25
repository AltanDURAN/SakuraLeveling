"""LE joueur de référence — définition unique, partagée par tous les calibrages.

Les monstres, les boss, les gardiens d'épreuve et le prix des artisans sont
tous calibrés « relativement à un joueur de ce niveau ». Chaque script avait sa
propre idée de ce qu'était ce joueur, et ces idées avaient divergé. Une seule
définition désormais : si elle change, tout se recalibre de façon cohérente.

Hypothèses, volontairement neutres :

  • **répartition équilibrée** — le joueur a `niveau - 1` points de stats et en
    place un tiers dans chacune des trois stats de base. C'est la seule
    hypothèse qui ne favorise aucun build ;
  • **équipement de son palier** — celui qu'un joueur assidu a réellement à ce
    niveau d'après la simulation de la saison (`GEAR_RARITY_CURVE`), plus
    l'arbre (`TREE_MAX_PCT`), stat par stat (`expected_percents`).
    Calibrer sur un joueur nu rendrait tout le contenu trivial dès qu'il
    s'équipe ; calibrer sur un joueur parfaitement optimisé le rendrait
    infranchissable pour tous les autres ;
  • **sauf au tout début** — un nouveau joueur n'a RIEN sur le dos : 0 % au
    niveau 1. Avant (audit d'octobre 2026), tout était calibré sur +50 % dès
    le niveau 1 : un compte neuf perdait 100 % de ses combats.
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

#: ÉQUIPEMENT v2 — rareté moyenne des 4 pièces « de base » (arme, bouclier,
#: tête, corps) d'un joueur assidu, par niveau. Points relevés sur la
#: simulation de la saison (taux de drop C, 30 min/jour, fusions dès que
#: possible) : 1 rare et 2 peu communes au niveau 16, une 1re épique vers 38,
#: une tenue presque légendaire vers 64. Valeur = multiplicateur moyen de
#: rareté (commun ×1 … légendaire ×4) ; le mythique, trop rare, est ignoré.
GEAR_RARITY_CURVE: tuple[tuple[int, float], ...] = (
    (1, 0.0), (8, 1.0), (16, 1.5), (23, 1.75), (38, 2.25), (54, 3.25), (64, 4.0),
)

#: % de la tenue équilibrée en COMMUN (arme ATK 8, bouclier DEF 6 / PV 4,
#: tête PV 6, corps DEF 6 / PV 6 — cf. items.json), multiplié par la rareté.
GEAR_KIT_COMMON_PCT = {"attack": 8.0, "defense": 12.0, "max_hp": 16.0}

#: L'arbre donne au plus +15 % d'ATK, de DEF et de PV (7 cases chacune) ;
#: on le suppose pris progressivement jusqu'au niveau `TREE_FULL_LEVEL`.
TREE_MAX_PCT = 15.0
TREE_FULL_LEVEL = 40

#: Vitesse de l'arbre : 6 cases à +0,5 (+3 au total), prises au même rythme.
#: Les monstres la suivent (restat_mobs) : sans ça, un joueur à 8 de vitesse
#: agissait 1,6 fois plus souvent qu'un monstre calibré à 5.
TREE_SPEED = 3.0


def _gear_rarity_multiplier(level: int) -> float:
    pts = GEAR_RARITY_CURVE
    if level <= pts[0][0]:
        return pts[0][1]
    for (l0, m0), (l1, m1) in zip(pts, pts[1:]):
        if level <= l1:
            return m0 + (m1 - m0) * (level - l0) / (l1 - l0)
    return pts[-1][1]


def expected_percents(level: int) -> dict[str, float]:
    """Bonus attendu (fraction, 0,25 = +25 %) sur ATK, DEF et PV à ce niveau :
    équipement de la simulation + arbre."""
    rarity = _gear_rarity_multiplier(level)
    tree = TREE_MAX_PCT * min(1.0, max(0, level - 1) / (TREE_FULL_LEVEL - 1))
    return {stat: (pct * rarity + tree) / 100 for stat, pct in GEAR_KIT_COMMON_PCT.items()}


#: Valeurs de départ des stats secondaires (miroir de StatsService).
BASE_SPEED = 5
BASE_CRIT_CHANCE = 5.0
BASE_CRIT_DAMAGE = 150.0
BASE_DODGE = 0.0
BASE_HP_REGENERATION = 5
BASE_MANA_MAX = 100
BASE_MANA_REGENERATION = 5


def expected_speed(level: int) -> int:
    """Vitesse attendue à ce niveau : base + cases de vitesse de l'arbre
    (tronquée, comme StatsService)."""
    tree = TREE_SPEED * min(1.0, max(0, level - 1) / (TREE_FULL_LEVEL - 1))
    return int(BASE_SPEED + tree)


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
    """Stats complètes du joueur de référence à ce niveau.

    `gear_percent` (fraction) impose un bonus UNIFORME (0 = joueur nu) ; par
    défaut, le bonus attendu stat par stat (`expected_percents`)."""
    points = base_points_at(level)
    if gear_percent is None:
        pct = expected_percents(level)
    else:
        pct = {"attack": gear_percent, "defense": gear_percent, "max_hp": gear_percent}
    f = {k: 1 + max(-0.9, v) for k, v in pct.items()}
    return Stats(
        max_hp=max(1, int((START_MAX_HP + MAX_HP_PER_POINT * points) * f["max_hp"])),
        attack=max(1, int((START_ATTACK + ATTACK_PER_POINT * points) * f["attack"])),
        defense=max(1, int((START_DEFENSE + DEFENSE_PER_POINT * points) * f["defense"])),
        speed=expected_speed(level),
        crit_chance=BASE_CRIT_CHANCE if crit_chance is None else crit_chance,
        crit_damage=BASE_CRIT_DAMAGE,
        dodge=BASE_DODGE if dodge is None else dodge,
        hp_regeneration=BASE_HP_REGENERATION,
        mana_max=BASE_MANA_MAX,
        mana_regeneration=BASE_MANA_REGENERATION,
    )
