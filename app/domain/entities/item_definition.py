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
    # Famille / panoplie de l'item (ex : "iron", "slime", "gobelin"). Vide
    # pour les items hors panoplie. Sert à calculer les bonus de set
    # (cf. SetBonusService et `sets.json`).
    family: str = ""

    @property
    def is_equipable(self) -> bool:
        return self.equipment_slot is not None