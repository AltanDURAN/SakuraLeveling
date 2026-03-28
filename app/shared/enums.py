from enum import StrEnum


class EquipmentSlot(StrEnum):
    WEAPON = "weapon"
    HELMET = "helmet"
    CHEST = "chest"
    BOOTS = "boots"
    RING_1 = "ring_1"
    RING_2 = "ring_2"


class ItemCategory(StrEnum):
    RESOURCE = "resource"
    WEAPON = "weapon"
    HELMET = "helmet"
    CHEST = "chest"
    BOOTS = "boots"
    RING = "ring"


class ItemRarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


class CooldownAction(StrEnum):
    DAILY = "daily"