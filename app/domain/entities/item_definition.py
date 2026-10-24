from dataclasses import dataclass
from datetime import datetime


@dataclass
class ItemDefinition:
    id: int
    code: str
    name: str
    description: str
    category: str
    rarity: str
    stackable: bool
    max_stack: int | None
    sell_price: int
    buy_price: int | None
    icon: str | None
    stat_bonuses: dict | None
    created_at: datetime
    updated_at: datetime
    # TYPE d'emplacement de l'item — `tete`, `corps`, `accessoire` ou `arme`
    # (cf. `ItemSlotType`), et non un emplacement précis : c'est
    # `EquipItemUseCase` qui choisit `accessoire_2` ou `arme_1` à la pose.
    # None = objet non équipable (ressource, consommable).
    equipment_slot: str | None = None
    # Vrai pour les armes/boucliers à 2 mains : ils occupent `arme_1` ET
    # verrouillent `arme_2`.
    requires_two_hands: bool = False
    # Ancienne famille de panoplie (saison 1 : les panoplies viennent des
    # raretés portées, cf. set_bonus_service). Plus lue ; conservée en base.
    family: str = ""
    # Niveau MINIMUM pour équiper la pièce. Les bonus étant des pourcentages du
    # socle, un objet de fin de jeu ne rend déjà pas un débutant surpuissant —
    # ce verrou protège autre chose : le PARCOURS. Sans lui, un nouveau joueur
    # à qui on offre une pièce ultime n'aurait plus jamais besoin d'en chercher,
    # elle grandirait toute seule avec lui.
    level_requirement: int = 1
    # Passif d'équipement (code de `gear_passives.PASSIVES`) — actif à partir
    # de l'épique. Vide pour tout ce qui n'est pas une pièce d'équipement.
    passive: str = ""

    def can_be_equipped_by(self, player_level: int) -> bool:
        return player_level >= max(1, self.level_requirement)

    @property
    def is_equipable(self) -> bool:
        return self.equipment_slot is not None