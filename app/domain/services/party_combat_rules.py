"""Règles et réglages du moteur de combat de groupe (constantes, escalade,
`EnemySetup`). Sortis de `party_combat_service.py` le 28/11/2026 (audit)."""

from dataclasses import dataclass, field

from app.domain.entities.mob_definition import MobDefinition


#: Escalade : à partir de la 30e action DU MONSTRE, puis toutes les 5, il se
#: renforce de +10 % × palier, PAR-DESSUS les paliers précédents (30e : ×1,1 ;
#: 35e : ×1,1×1,2 ; 40e : ×1,1×1,2×1,3…). Comptée en actions du MONSTRE
#: (25/10/2026) : comptée en actions de tout le monde, elle arrivait 3 fois
#: plus tôt à 3 joueurs et favorisait ceux qui tuent vite (les DPS). En solo,
#: c'est le même moment qu'avant (~50 actions au total). Seules ses stats
#: OFFENSIVES montent (attaque, défense, vitesse, critiques) : augmenter ses
#: PV ou son esquive rallongerait le combat, l'inverse du but — et les PV d'un
#: world boss sont conservés d'un jour à l'autre. Contre un GROUPE d'ennemis,
#: chacun compte ses propres actions.
ESCALATION_START = 25    # 1er palier à la 30e action du monstre (25 + 5)
ESCALATION_EVERY = 5
ESCALATION_STEP = 0.10

#: Garde-fou absolu du nombre d'actions, en dernier recours si l'escalade ne
#: suffit pas (ex. Soigneurs qui soignent tout). Atteint ⇒ monstre non vaincu.
#: Multiplié par le nombre d'ennemis (chacun agit).
HARD_MAX_TURNS = 500

#: Aggro : un monstre vise de préférence le joueur le plus SOLIDE (PV max +
#: DEF × 25, la robustesse du power score), poids à la puissance 3 — un tank
#: deux fois plus robuste qu'un DPS prend 8 fois plus de coups que lui. Avant
#: (25/10/2026), la cible était tirée au hasard : le tank ne protégeait
#: personne. La provocation reste prioritaire.
THREAT_DEF_WEIGHT = 25
THREAT_EXPONENT = 3

#: Sève vénéneuse : le poison d'un tour vaut 1 % des PV max de l'ennemi,
#: plafonné à 25 % de l'ATK du porteur — sans plafond, contre un boss ou une
#: élite à ×20 PV, il frappait plus fort que le porteur lui-même.
ROOT_VENOM_PCT = 1
ROOT_VENOM_ATK_CAP_PCT = 25


def escalation_multiplier(mob_actions: int) -> float:
    """Multiplicateur cumulé des stats du monstre après `mob_actions` actions
    du monstre."""
    mult = 1.0
    for level in range(1, max(0, mob_actions - ESCALATION_START) // ESCALATION_EVERY + 1):
        mult *= 1 + ESCALATION_STEP * level
    return mult


@dataclass
class EnemySetup:
    """Un ennemi d'un combat de groupe (`fight_party_vs_mobs`).

    `elemental_out` / `elemental_in` : multiplicateurs élémentaires PAR
    JOUEUR contre cet ennemi (ses dégâts infligés / reçus). Les modificateurs
    de boss (immunité, soin, renvoi, invocations) sont propres à l'ennemi."""

    mob: MobDefinition
    abilities: dict = field(default_factory=dict)
    elemental_out: dict[int, float] = field(default_factory=dict)
    elemental_in: dict[int, float] = field(default_factory=dict)
    is_boss: bool = False
    #: Élément d'attaque infusé de chaque joueur contre cet ennemi (affichage).
    infusion: dict[int, str] = field(default_factory=dict)
    immunity_threshold: int = 0
    heal_per_turn: int = 0
    reflect_pct: int = 0
    adds: dict | None = None
    # --- World boss (27/10/2026, mécaniques A, B et C validées par l'auteur)
    #: Le combat s'arrête quand CET ennemi tombe (le boss), gardes ou non.
    decisive: bool = False
    #: Garde du boss : les joueurs le visent d'abord ; tant qu'un garde est
    #: debout, le boss subit `guarded_reduction_pct` % de dégâts en moins.
    guard: bool = False
    guarded_reduction_pct: int = 0
    #: Phases : [{below_pct, name, text, attack_pct, abilities}] — sous ce
    #: seuil de PV, l'ennemi gagne ces capacités (annoncé en combat).
    phases: list[dict] = field(default_factory=list)
    #: Attaque ultime : {name, every, multiplier, charge} — une action de
    #: charge annoncée, puis un coup énorme sur tout le groupe… sauf si un
    #: joueur le provoque : il l'encaisse seul (×1,5).
    ultimate: dict | None = None


#: L'ultime intercepté par une provocation frappe ce provocateur seul, plus fort.
ULTIMATE_SINGLE_MULT = 1.5
