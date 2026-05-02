"""Définition statique d'un world boss (chargée depuis le JSON content).

Une `BossDefinition` est immuable et décrit ce qu'un boss EST. L'instance
combattue actuellement vit dans la table `world_bosses` (entité `WorldBoss`)
qui peut être créée à partir d'une `BossDefinition`.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BossDefinition:
    code: str
    name: str
    description: str
    image_name: str
    tier: str  # "intro" | "medium" | "medium_hard" | "hard" | "endgame"
    spawn_weight: int  # poids pour la sélection aléatoire (plus grand = plus probable)

    max_hp: int
    attack: int
    defense: int
    speed: int
    crit_chance: int
    crit_damage: int
    dodge: int

    # Particularités du boss. Tous les modifiers sont optionnels et ignorés
    # poliment s'ils ne sont pas connus du moteur — facilite l'extension.
    #   damage_immunity_threshold (int) : ignore les dégâts < N
    #   enrage_below_pct (int 0-100)    : enragé sous X% PV restants
    #   enrage_attack_multiplier (float): multiplicateur d'attaque en rage
    #   crit_immunity (bool)            : annule l'effet des crits joueurs
    modifiers: dict = field(default_factory=dict)

    lore: str = ""
