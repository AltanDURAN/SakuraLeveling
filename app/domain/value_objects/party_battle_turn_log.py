from dataclasses import dataclass, field


@dataclass
class PartyBattleTurnLog:
    turn_number: int
    player_actions: list[str]
    mob_action: str
    players_state: list[dict]
    mob_state: dict
    #: Combat contre plusieurs ennemis : l'état de chacun, dans l'ordre de la
    #: formation (vide contre un seul ennemi — `mob_state` suffit).
    enemies_state: list[dict] = field(default_factory=list)
