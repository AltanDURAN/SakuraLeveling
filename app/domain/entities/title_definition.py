"""Définition statique d'un titre (chargée depuis le JSON content).

Un titre se débloque par une condition (kills_family, kills_total, etc.)
et confère un effet passif (bonus damage vs famille, reduction damage from
famille, etc.). Le code est l'identifiant stable utilisé en DB et dans
l'autocomplete.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TitleDefinition:
    code: str
    name: str
    description: str
    icon: str  # emoji affiché dans /profile

    # Condition de débloquage. Les types supportés en V1 :
    #   "kills_family"  : target=family (ex "slime"), value=count requis
    #   "kills_total"   : value=count requis (toutes familles confondues)
    #   "duels_won"     : value=count requis
    #   "items_crafted" : value=count requis
    condition_type: str
    condition_target: str = ""
    condition_value: int = 0

    # Effets passifs (appliqués automatiquement dès le titre débloqué).
    # Format : `effects` = liste de dict {type, target, value}.
    # Types V1 :
    #   "damage_bonus_vs_family"     : target=family, value=pct (ex 10 = +10%)
    #   "damage_reduction_from_family": target=family, value=pct
    effects: list[dict] = field(default_factory=list)
