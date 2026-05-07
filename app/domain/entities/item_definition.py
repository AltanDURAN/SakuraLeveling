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
    # Slot principal où l'item peut être équipé (None = non équipable).
    # Pour les armes 1-main, ce slot est le défaut mais on peut équiper en
    # OFF_HAND aussi (ambidextrie gérée dans EquipItemUseCase).
    equipment_slot: str | None = None
    # Vrai pour les armes à 2 mains qui occupent MAIN_HAND + OFF_HAND.
    requires_two_hands: bool = False
    # Famille / panoplie de l'item (ex : "iron", "slime", "gobelin"). Vide
    # pour les items hors panoplie. Sert à calculer les bonus de set
    # (cf. SetBonusService et `sets.json`).
    family: str = ""

    @property
    def is_equipable(self) -> bool:
        return self.equipment_slot is not None