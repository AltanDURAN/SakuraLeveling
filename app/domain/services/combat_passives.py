"""Passifs de combat et classes de l'arbre de compétences — SAISON 1.

Les cases « passif » et « classe » de l'arbre portent des effets qui ne sont
pas des stats : ils changent la façon dont un combat se déroule (bouclier
d'ouverture, provocation, soin à la place de l'attaque…). Ils sont agrégés ici
en un `CombatPassives` par joueur, que le moteur de combat (`PartyCombatService`)
lit.

Toutes les valeurs sont des POURCENTAGES entiers (10 = 10 %), sauf les drapeaux
(1 = actif) et `heal_power_multiplier` (×2 = double).

Règles décidées avec l'auteur (octobre 2026) :
  • les réductions de dégâts reçus de toutes les cases S'ADDITIONNENT
    (Résistant 10 % + Titan 5 % = 15 %), plafonnées à `MAX_DAMAGE_REDUCTION` ;
  • tous les passifs s'appliquent PARTOUT (groupe, world boss, épreuves de
    rang, défis) — ceux qui concernent des alliés n'ont pas d'effet seul.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Soin de base du sort de soin (classe Soigneur), en % de l'ATTAQUE du lanceur.
#: Le Soigneur le double (`heal_power_multiplier`).
BASE_HEAL_PCT = 50

#: Le sort de soin ne vise qu'un allié sous ce % de ses PV ; sinon le Soigneur
#: attaque. Avant (25/10/2026), il soignait dès qu'il manquait 1 PV : seul, il
#: ne frappait presque jamais (0 % de victoires en solo).
HEAL_BELOW_PCT = 50

#: Plafond technique des réductions de dégâts cumulées. L'auteur veut être
#: prévenu au-delà de 25 % (alerte du builder) ; au-delà de 80 % un combat
#: n'aurait plus de sens.
DAMAGE_REDUCTION_WARNING = 25
MAX_DAMAGE_REDUCTION = 80

#: Mage : multiplie le GAIN de l'infusion élémentaire selon l'affinité dans
#: l'élément de l'attaque : 25 → ×1,25 · 50 → ×1,5 · 100 → ×2.
#: ⚠️ Avant (25/10/2026), il multipliait les DÉGÂTS ENTIERS (×1,5 / ×2 / ×5) :
#: contre un monstre faible à son élément, à 100 d'affinité, ×1,6 d'infusion
#: × 5 = ×8 — une élite de groupe tombait en 2 actions, même à trois DPS.
#: Désormais ×2,2 au lieu de ×1,6 (+37 %, l'ordre de l'Assassin), et
#: seulement quand il y a infusion.
MAGE_AFFINITY_TIERS: tuple[tuple[int, float], ...] = ((100, 2.0), (50, 1.5), (25, 1.25))

# ------------------------------------------------------------------ mana --
#: Coût en mana des compétences ACTIVES (25/10/2026, demande de l'auteur).
#: Tout ce qui INTERVIENT dans le combat — soin, bouclier, provocation,
#: riposte, coup supplémentaire, protection d'un allié, sauvetage — puise dans
#: la réserve, AUTOMATIQUEMENT et seulement quand l'effet sert (soin : un
#: allié est blessé ; Vampire : il lui manque des PV ; provocation : il y a
#: quelqu'un à protéger). Réserve vide ⇒ l'effet ne se déclenche pas (le
#: Soigneur attaque à la place). Les simples modificateurs (bonus de dégâts,
#: réductions, critiques, pénétration, cumuls…) restent gratuits.
#: Le mana ne remonte JAMAIS en combat : c'est la régénération hors combat
#: qui décide combien de combats d'affilée on tient à plein régime.
#:
#: CALIBRÉ le 25/10/2026 (`python -m scripts.measure_mana`, builds de rôle) :
#:   • prix ∝ ce que rapporte UN déclenchement, mesuré dans les combats
#:     d'élite — sort de soin ≈ 160-180 PV (ancre : 9), Coup double ≈ 1,1 à
#:     1,5 soin (≈ 540 dégâts × 0,4 PV par dégât), Clerc ≈ 1/5 de soin,
#:     Vampire ≈ 1/6, Riposte ≈ 1/4, Rempart ≈ 55 PV DÉPLACÉS vers le tank
#:     (pas épargnés : compté ~1/5) ;
#:   • une fois par combat (Égide, Tenace, Revenant, Défi, Garde) : un droit
#:     d'entrée selon la puissance, jamais plus d'un quart de la réserve de
#:     base — au prix de leur valeur, Revenant dépasserait la réserve d'un tank ;
#:   • l'ancre fixe le BUDGET : un combat d'élite vide 66 à 89 % de la réserve
#:     du soigneur et jusqu'à ~100 % de celle du tank, sans changer l'issue
#:     (élites gagnées à 100 % réserve pleine) ; le farm coûte ≤ 14 mana par
#:     combat, moins que 3 min de régénération ; un long world boss épuise le
#:     soigneur (assauts inchangés, ~6).
MANA_COSTS: dict[str, int] = {
    "heal_spell": 9,        # Soigneur : sort de soin
    "ally_heal": 2,         # Clerc : soin de l'allié le plus blessé
    "lifesteal": 1,         # Vampire
    "taunt": 4,             # Vaillant : provocation
    "team_shield": 20,      # Égide : bouclier de groupe (début de combat)
    "redirect": 2,          # Rempart : encaisse une part du coup d'un allié
    "last_stand": 12,       # Tenace : tient à 1 PV
    "counter_attack": 3,    # Riposte
    "double_strike": 12,    # Coup double
    "taunt_guard": 6,       # Défi : provocation d'ouverture
    "undying": 25,          # Revenant
    "first_hit_ward": 6,    # Garde de l'exil
}

#: Nom joueur de chaque compétence à mana (journal, aide).
MANA_ABILITY_NAMES: dict[str, str] = {
    "heal_spell": "Sort de soin", "ally_heal": "Clerc", "lifesteal": "Vampire",
    "taunt": "Vaillant", "team_shield": "Égide", "redirect": "Rempart",
    "last_stand": "Tenace", "counter_attack": "Riposte", "double_strike": "Coup double",
    "taunt_guard": "Défi", "undying": "Revenant", "first_hit_ward": "Garde de l'exil",
}

#: Effet de l'arbre (type JSON) ou passif d'équipement (code) → compétence à mana.
MANA_ABILITY_OF_EFFECT: dict[str, str] = {
    "healer_spell": "heal_spell", "ally_heal_on_hit_percent": "ally_heal",
    "lifesteal_percent": "lifesteal", "taunt_chance_percent": "taunt",
    "team_shield_percent": "team_shield", "redirect_ally_damage_percent": "redirect",
    "last_stand": "last_stand", "counter_attack": "counter_attack",
    "double_strike": "double_strike", "taunt_guard": "taunt_guard",
    "undying": "undying", "first_hit_ward": "first_hit_ward",
}


#: Ce que paie le coût (« 6 mana par soin »).
_MANA_UNIT: dict[str, str] = {
    "heal_spell": "soin", "ally_heal": "soin", "lifesteal": "vol de vie",
    "taunt": "provocation", "team_shield": "combat", "redirect": "coup encaissé",
    "last_stand": "sauvetage", "counter_attack": "riposte", "double_strike": "coup double",
    "taunt_guard": "combat", "undying": "résurrection", "first_hit_ward": "combat",
}


def mana_cost_text(effect_or_passive: str) -> str:
    """« 💧 6 mana par soin » pour un effet de l'arbre ou un passif
    d'équipement à mana, sinon ""."""
    ability = MANA_ABILITY_OF_EFFECT.get(effect_or_passive)
    cost = MANA_COSTS.get(ability, 0) if ability else 0
    return f"💧 {cost} mana par {_MANA_UNIT.get(ability, 'usage')}" if cost else ""

# ------------------------------------------------------------- tactiques --
#: Tactique de combat, choisie par le joueur HORS combat (`/tactique`) et figée
#: pendant le combat. Elle décide aujourd'hui de la cible du sort de soin ;
#: d'autres comportements pourront s'y brancher.
TACTICS: dict[str, tuple[str, str]] = {
    "egoiste": ("Égoïste", "Se soigne d'abord s'il est sous 50 % de ses PV ; sinon, l'allié le plus blessé."),
    "pragmatique": ("Pragmatique", "Parmi les alliés sous 50 % de PV, soigne celui qui encaisse le plus."),
    "all_in": ("All-in", "Parmi les alliés sous 50 % de PV, soigne celui qui inflige le plus de dégâts."),
}
DEFAULT_TACTIC = "egoiste"


def normalize_tactic(value: str | None) -> str:
    return value if value in TACTICS else DEFAULT_TACTIC


# ----------------------------------------------------- fonctionnalités --
#: Fonctionnalités débloquées par les cases « Confort » (effet `unlock_feature`).
FEATURES: dict[str, str] = {
    "notify_cooldowns": "Message privé quand un temps de recharge est terminé",
    "notify_events": "Message privé quand un événement apparaît",
    "tower_bonus_ticket": "+1 ticket par jour pour la tour solo (non cumulable)",
}


@dataclass(frozen=True)
class CombatPassives:
    """Effets de combat d'un joueur (somme des cases investies au maximum)."""

    damage_dealt_pct: float = 0.0          # Titan
    damage_taken_reduction_pct: float = 0.0  # Résistant, Titan
    armor_penetration_pct: float = 0.0     # Léthal : ignore X % de la défense
    last_stand: bool = False               # Tenace : 1er coup fatal → 1 PV
    taunt_chance_pct: float = 0.0          # Vaillant : chance de provoquer à chaque attaque
    splash_damage_pct: float = 0.0         # AOE : dégâts aux ennemis adjacents
    team_shield_pct: float = 0.0           # Égide : bouclier (% de SES PV max) à tous
    redirect_ally_damage_pct: float = 0.0  # Rempart : encaisse X % des coups des alliés
    lifesteal_pct: float = 0.0             # Vampire : se soigne de X % des dégâts infligés
    heal_received_pct: float = 0.0         # Paladin : soins reçus +X %
    healer: bool = False                   # Soigneur : le sort de soin remplace l'attaque
    team_damage_pct: float = 0.0           # Soigneur : aura, +X % de dégâts à toute l'équipe
    threat_pct: float = 0.0                # Gardien : robustesse comptée +X % pour l'aggro
    ally_heal_on_hit_pct: float = 0.0      # Clerc : X % des dégâts infligés soignent l'allié le plus blessé
    heal_power_multiplier: float = 1.0     # Soigneur : ×2 sur les soins donnés
    heal_buff_pct: float = 0.0             # Buff : un soin donne +X % ATK/DEF (cible + soi)
    speed_per_ally: int = 0                # Soigneur : +1 vitesse par allié présent
    mage: bool = False                     # Mage : ×1,5 / ×2 / ×5 selon l'affinité
    classes: tuple[str, ...] = field(default_factory=tuple)
    #: Passifs d'ÉQUIPEMENT actifs (pièces épiques et plus), cf. gear_passives.
    gear: frozenset[str] = field(default_factory=frozenset)

    def has(self, gear_passive: str) -> bool:
        return gear_passive in self.gear

    @property
    def damage_reduction_fraction(self) -> float:
        return min(MAX_DAMAGE_REDUCTION, max(0.0, self.damage_taken_reduction_pct)) / 100.0

    @property
    def is_empty(self) -> bool:
        return self == CombatPassives(classes=self.classes)


NO_PASSIVES = CombatPassives()


def mage_multiplier(affinity: int | float | None) -> float:
    """Multiplicateur du GAIN élémentaire du Mage pour une affinité dans
    l'élément de l'attaque (palier le plus haut atteint)."""
    value = float(affinity or 0)
    for threshold, mult in MAGE_AFFINITY_TIERS:
        if value >= threshold:
            return mult
    return 1.0


def outgoing_elemental_multiplier(
    infusion_multiplier: float,
    infusion_element: str,
    affinities: dict | None,
    passives: CombatPassives | None,
) -> float:
    """Multiplicateur élémentaire sortant, Mage compris.

    Le Mage n'a de bonus que si une infusion a lieu (le monstre a une
    faiblesse exploitable) : contre un monstre neutre, rien. Il amplifie le
    GAIN (infusion − 1), jamais les dégâts entiers.
    """
    mult = infusion_multiplier if infusion_element else 1.0
    if passives is not None and passives.mage and infusion_element and mult > 1.0:
        mult = 1.0 + (mult - 1.0) * mage_multiplier((affinities or {}).get(infusion_element, 0))
    return mult
