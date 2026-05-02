from dataclasses import dataclass


@dataclass
class DuelTurnLog:
    """Log d'un tour de duel 1v1 entre deux joueurs (a vs b).

    `actor` indique qui a frappé ce tour (`"a"` ou `"b"`). Les HP after
    sont l'état des deux joueurs immédiatement après l'action — utile pour
    l'animation Discord qui édite l'embed à chaque tour.
    """

    turn_number: int
    actor: str  # "a" ou "b"
    damage: int
    is_crit: bool
    target_dodged: bool
    a_hp_after: int
    b_hp_after: int


@dataclass
class DuelResult:
    """Résultat d'un duel 1v1.

    `winner` vaut `"a"` ou `"b"`. `a_max_hp` et `b_max_hp` sont nécessaires
    pour rendre les barres de vie côté embed. Ces deux valeurs sont aussi
    les HP de départ : un duel commence toujours full HP.
    """

    winner: str
    turns: int
    a_remaining_hp: int
    b_remaining_hp: int
    a_max_hp: int
    b_max_hp: int
    turn_logs: list[DuelTurnLog]
