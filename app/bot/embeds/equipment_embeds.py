"""Embeds pour /equipment : affichage 2 pages des slots d'équipement."""

import discord

from app.domain.entities.player_equipment_item import PlayerEquipmentItem
from app.shared.enums import EquipmentSlot, PRIMARY_SLOTS, SECONDARY_SLOTS


SLOT_ICONS: dict[str, str] = {
    EquipmentSlot.HELMET.value: "⛑️",
    EquipmentSlot.CHEST.value: "👕",
    EquipmentSlot.LEGS.value: "👖",
    EquipmentSlot.BOOTS.value: "🥾",
    EquipmentSlot.MAIN_HAND.value: "🗡️",
    EquipmentSlot.OFF_HAND.value: "🛡️",
    EquipmentSlot.NECKLACE.value: "📿",
    EquipmentSlot.BRACELET.value: "⛓️",
    EquipmentSlot.RING.value: "💍",
    EquipmentSlot.BELT.value: "🎗️",
    EquipmentSlot.CAPE.value: "🧣",
    EquipmentSlot.EARRING.value: "👂",
}

SLOT_LABELS: dict[str, str] = {
    EquipmentSlot.HELMET.value: "Casque",
    EquipmentSlot.CHEST.value: "Plastron",
    EquipmentSlot.LEGS.value: "Jambières",
    EquipmentSlot.BOOTS.value: "Bottes",
    EquipmentSlot.MAIN_HAND.value: "Main droite",
    EquipmentSlot.OFF_HAND.value: "Main gauche",
    EquipmentSlot.NECKLACE.value: "Collier",
    EquipmentSlot.BRACELET.value: "Bracelet",
    EquipmentSlot.RING.value: "Bague",
    EquipmentSlot.BELT.value: "Ceinture",
    EquipmentSlot.CAPE.value: "Cape",
    EquipmentSlot.EARRING.value: "Boucle d'oreille",
}


def _format_stat_bonuses(stat_bonuses: dict | None) -> str:
    """Formate '+5 atk, +10 PV' pour affichage compact."""
    if not stat_bonuses:
        return ""

    short_labels = {
        "max_hp": "PV",
        "attack": "atk",
        "defense": "def",
        "speed": "vit",
        "crit_chance": "crit",
        "crit_damage": "dmg crit",
        "dodge": "esq",
        "hp_regeneration": "regen",
    }
    parts = [
        f"+{value} {short_labels.get(key, key)}"
        for key, value in stat_bonuses.items()
        if value
    ]
    return " · ".join(parts)


def _format_slot_line(
    slot: str,
    equipped: PlayerEquipmentItem | None,
    two_handed_locked: bool = False,
) -> str:
    icon = SLOT_ICONS.get(slot, "•")
    label = SLOT_LABELS.get(slot, slot)

    if two_handed_locked:
        return f"{icon} **{label}** : _verrouillée par l'arme à 2 mains_"

    if equipped is None:
        return f"{icon} **{label}** : _vide_"

    item = equipped.item_definition
    bonuses = _format_stat_bonuses(item.stat_bonuses)
    suffix = f"  ·  {bonuses}" if bonuses else ""
    return f"{icon} **{label}** : {item.name}{suffix}"


def _build_page(
    title: str,
    target_name: str,
    slots: list[EquipmentSlot],
    equipped_by_slot: dict[str, PlayerEquipmentItem],
    main_hand_two_handed: bool,
    page_number: int,
    total_pages: int,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🛡️ Équipement de {target_name} — {title}",
        color=discord.Color.purple(),
    )

    lines: list[str] = []
    for slot in slots:
        slot_value = slot.value
        equipped = equipped_by_slot.get(slot_value)

        # OFF_HAND est verrouillée si MAIN_HAND a une arme 2-mains
        two_handed_locked = (
            slot_value == EquipmentSlot.OFF_HAND.value and main_hand_two_handed
        )
        lines.append(_format_slot_line(slot_value, equipped, two_handed_locked))

    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Page {page_number} / {total_pages}")
    return embed


def build_primary_equipment_embed(
    target_name: str,
    equipped_items: list[PlayerEquipmentItem],
) -> discord.Embed:
    by_slot = {item.slot: item for item in equipped_items}
    main_hand = by_slot.get(EquipmentSlot.MAIN_HAND.value)
    main_hand_two_handed = (
        main_hand is not None and main_hand.item_definition.requires_two_hands
    )
    return _build_page(
        title="Principaux",
        target_name=target_name,
        slots=PRIMARY_SLOTS,
        equipped_by_slot=by_slot,
        main_hand_two_handed=main_hand_two_handed,
        page_number=1,
        total_pages=2,
    )


def build_secondary_equipment_embed(
    target_name: str,
    equipped_items: list[PlayerEquipmentItem],
) -> discord.Embed:
    by_slot = {item.slot: item for item in equipped_items}
    return _build_page(
        title="Secondaires",
        target_name=target_name,
        slots=SECONDARY_SLOTS,
        equipped_by_slot=by_slot,
        main_hand_two_handed=False,
        page_number=2,
        total_pages=2,
    )


PAGES = [
    ("⚔️ Principaux", build_primary_equipment_embed),
    ("💎 Secondaires", build_secondary_equipment_embed),
]
