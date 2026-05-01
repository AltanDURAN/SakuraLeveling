from dataclasses import dataclass, field

from app.domain.value_objects.player_reward import PlayerReward


@dataclass
class BattleSummary:
    """Résumé d'un combat pour affichage et persistance.

    `outcome` est l'un de : "victory", "defeat", "flee".
    `flee` correspond à l'absence de participants : pas de combat ni de récompense.
    """

    outcome: str
    mob_name: str
    mob_image_name: str | None
    mob_family: str
    turns: int
    rewards: list[PlayerReward] = field(default_factory=list)
    base_xp_reward: int = 0
    base_gold_reward: int = 0

    @property
    def is_victory(self) -> bool:
        return self.outcome == "victory"

    @property
    def is_defeat(self) -> bool:
        return self.outcome == "defeat"

    @property
    def is_flee(self) -> bool:
        return self.outcome == "flee"
