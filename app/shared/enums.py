from enum import StrEnum


class EquipmentSlot(StrEnum):
    """Slots d'équipement (12 slots au total : 6 principaux + 6 secondaires).

    Les noms sont en français pour cohérence avec l'UI joueur.
    """

    # Slots principaux (page 1 de /equipment)
    HELMET = "casque"
    CHEST = "plastron"
    LEGS = "jambieres"
    BOOTS = "bottes"
    MAIN_HAND = "main_droite"
    OFF_HAND = "main_gauche"

    # Slots secondaires (page 2 de /equipment)
    NECKLACE = "collier"
    BRACELET = "bracelet"
    RING = "bague"
    BELT = "ceinture"
    CAPE = "cape"
    EARRING = "boucle_oreille"


PRIMARY_SLOTS: list[EquipmentSlot] = [
    EquipmentSlot.HELMET,
    EquipmentSlot.CHEST,
    EquipmentSlot.LEGS,
    EquipmentSlot.BOOTS,
    EquipmentSlot.MAIN_HAND,
    EquipmentSlot.OFF_HAND,
]

SECONDARY_SLOTS: list[EquipmentSlot] = [
    EquipmentSlot.NECKLACE,
    EquipmentSlot.BRACELET,
    EquipmentSlot.RING,
    EquipmentSlot.BELT,
    EquipmentSlot.CAPE,
    EquipmentSlot.EARRING,
]

# Slots où une arme à 1 main peut être équipée (ambidextrie)
WEAPON_HAND_SLOTS: list[EquipmentSlot] = [
    EquipmentSlot.MAIN_HAND,
    EquipmentSlot.OFF_HAND,
]


class ItemCategory(StrEnum):
    RESOURCE = "resource"
    WEAPON = "weapon"
    SHIELD = "shield"
    HELMET = "helmet"
    CHEST = "chest"
    LEGS = "legs"
    BOOTS = "boots"
    NECKLACE = "necklace"
    BRACELET = "bracelet"
    RING = "ring"
    BELT = "belt"
    CAPE = "cape"
    EARRING = "earring"


class ItemRarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


class CooldownAction(StrEnum):
    DAILY = "daily"
