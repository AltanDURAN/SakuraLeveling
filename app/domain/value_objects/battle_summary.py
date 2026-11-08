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
    #: « zone » (combat de groupe) ou « tour » (tour solo, 08/11/2026) : la
    #: tour n'a ni or partagé ni part de victoire.
    kind: str = "zone"
    #: Lignes en tête de la page Récompenses (tour : record, ticket).
    notes: list[str] = field(default_factory=list)
    #: État final des ennemis {name, max_hp, remaining_hp, defeated} : page
    #: Détails de la tour (ce qu'il leur restait).
    enemies: list[dict] = field(default_factory=list)

    @property
    def is_tower(self) -> bool:
        return self.kind == "tour"

    @property
    def is_victory(self) -> bool:
        return self.outcome == "victory"

    @property
    def is_defeat(self) -> bool:
        return self.outcome == "defeat"
