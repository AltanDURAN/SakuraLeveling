"""Mappings centralisés stat → emoji.

Permet d'avoir une source unique pour tous les rendus (cogs, embeds,
images Pillow). Ajouter une nouvelle stat = ajouter une entrée ici, et
elle apparaît partout cohérente.

Deux dictionnaires :
- `STAT_EMOJIS` : clés "stat" génériques (`max_hp`, `attack`, ...) — utilisées
  par `Stats` VO et le JSON `stat_bonuses` des items.
- `BONUS_EMOJIS` : clés "bonus" suffixées `_flat` — utilisées par les
  paliers de panoplie (`defense_flat`, `dodge_flat`, ...).
"""

from __future__ import annotations


STAT_EMOJIS: dict[str, str] = {
    "max_hp":          "❤️",
    "attack":          "⚔️",
    "defense":         "🛡️",
    "speed":           "💨",
    "crit_chance":     "🎯",
    "crit_damage":     "💥",
    "dodge":           "🌀",
    "hp_regeneration": "✨",
}

BONUS_EMOJIS: dict[str, str] = {
    "max_hp_flat":         "❤️",
    "attack_flat":         "⚔️",
    "defense_flat":        "🛡️",
    "speed_flat":          "💨",
    "crit_chance_flat":    "🎯",
    "crit_damage_flat":    "💥",
    "dodge_flat":          "🌀",
    "hp_regeneration_flat": "✨",
}


def stat_emoji(stat_key: str) -> str:
    """Récupère l'emoji d'une stat ; renvoie la clé brute si absente."""
    return STAT_EMOJIS.get(stat_key, stat_key)


def bonus_emoji(bonus_type: str) -> str:
    """Récupère l'emoji d'un type de bonus ; renvoie la clé brute si
    absente."""
    return BONUS_EMOJIS.get(bonus_type, bonus_type)


def item_display_emoji(item) -> str:
    """Emoji représentatif d'un item pour les listes (panoplie, etc).

    - weapon 1H → 🗡️ ; weapon 2H → ⚔️
    - shield → 🛡️
    - sinon : emoji du slot canonique (casque, cape, etc.)
    Le caller passe directement un `ItemDefinition` (canard typing).
    """
    cat = getattr(item, "category", None)
    if cat == "shield":
        return "🛡️"
    if cat == "weapon":
        return "⚔️" if getattr(item, "requires_two_hands", False) else "🗡️"
    # Lazy import pour éviter le cycle si SLOT_ICONS bouge un jour
    from app.shared.enums import SLOT_ICONS
    slot = getattr(item, "equipment_slot", None) or ""
    return SLOT_ICONS.get(slot, "📦")


def format_stat_bonuses_short(stat_bonuses: dict | None) -> str:
    """Bonus compact `+N {emoji} · -M {emoji}` — utilisé par les rendus
    d'items (panoplie, equipement). Les valeurs négatives gardent leur
    signe natif (pas de double "+-")."""
    if not stat_bonuses:
        return ""
    parts = []
    for k, v in stat_bonuses.items():
        if not v:
            continue
        sign = "+" if v > 0 else ""
        parts.append(f"{sign}{v} {stat_emoji(k)}")
    return " · ".join(parts)
