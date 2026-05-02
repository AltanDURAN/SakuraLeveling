from dataclasses import dataclass
from datetime import datetime


@dataclass
class DuelRank:
    """Position d'un joueur dans le classement 1v1.

    `rank_position` : entier ≥ 1, plus petit = mieux classé. La règle de
    challenge l'utilise comme référence : un joueur ne peut défier qu'un
    autre joueur strictement mieux classé que lui (rank_position plus
    petit). Si le challenger gagne, les deux positions sont échangées.
    """

    player_id: int
    rank_position: int
    wins: int
    losses: int
    created_at: datetime
    updated_at: datetime
