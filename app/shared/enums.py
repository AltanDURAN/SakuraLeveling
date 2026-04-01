from enum import Enum


class EquipmentSlot(str, Enum):
    WEAPON = "weapon"
    HELMET = "helmet"
    CHEST = "chest"
    BOOTS = "boots"
    RING_1 = "ring_1"
    RING_2 = "ring_2"


class ItemCategory(str, Enum):
    RESOURCE = "resource"
    WEAPON = "weapon"
    HELMET = "helmet"
    CHEST = "chest"
    BOOTS = "boots"
    RING = "ring"


class ItemRarity(str, Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


class CooldownAction(str, Enum):
    DAILY = "daily"