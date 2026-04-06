from dataclasses import dataclass

from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog


@dataclass
class PartyBattleResult:
    victory: bool
    turns: int
    mob_name: str
    mob_image_url: str | None
    mob_remaining_hp: int
    surviving_players: list[str]
    defeated_players: list[str]
    xp_gained: int
    gold_gained: int
    summary: str
    turn_logs: list[PartyBattleTurnLog]