from dataclasses import dataclass, field

from app.domain.value_objects.player_reward import PlayerReward


@dataclass
class BattleSummary:
    """Résumé d'un combat pour affichage et persistance.

    `outcome` est l'un de : "victory", "defeat".
    """

    outcome: str
    mob_name: str
    mob_image_name: str | None
    mob_family: str
    turns: int
    rewards: list[PlayerReward] = field(default_factory=list)
    base_xp_reward: int = 0
    base_gold_reward: int = 0
    #: Le déroulé du combat, une ligne par action (3e page du récapitulatif :
    #: la vidéo a remplacé le message « combat en cours »).
    journal: list[str] = field(default_factory=list)
    #: Événement lunaire du combat (« 🌕 Pleine lune — … »), vide sinon.
    lunar_note: str = ""
    #: Nombre de monstres (une meute en compte plusieurs).
    mob_count: int = 1

    @property
    def is_victory(self) -> bool:
        return self.outcome == "victory"

    @property
    def is_defeat(self) -> bool:
        return self.outcome == "defeat"
