from dataclasses import dataclass


@dataclass
class PartyBattleTurnLog:
    turn_number: int
    player_actions: list[str]
    mob_action: str
    party_hp_summary: str
    mob_hp_after: int