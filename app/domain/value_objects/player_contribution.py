from dataclasses import dataclass, field


@dataclass
class PlayerContribution:
    player_id: int
    user_id: int
    name: str
    damage_dealt: int = 0
    damage_tanked: int = 0
    hp_healed: int = 0
    dodges: int = 0
    survived: bool = True
    final_hp: int = 0
    max_hp: int = 0
    # Mana restant en fin de combat (persisté hors combat pour la régen).
    final_mana: int = 0
    mana_max: int = 0
    # Mana dépensé par les compétences actives (cf. combat_passives.MANA_COSTS).
    mana_spent: int = 0
    # Déclenchements par compétence : {"heal_spell": 5, …} ; `mana_dry` =
    # déclenchements ratés faute de mana.
    mana_uses: dict = field(default_factory=dict)
    mana_dry: int = 0
