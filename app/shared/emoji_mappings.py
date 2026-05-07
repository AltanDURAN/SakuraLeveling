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


def format_stat_bonuses_short(stat_bonuses: dict | None) -> str:
    """Bonus compact `+N {emoji}  ·  +M {emoji}` — utilisé par les
    rendus d'items (panoplie, equipement)."""
    if not stat_bonuses:
        return ""
    parts = [
        f"+{v} {stat_emoji(k)}"
        for k, v in stat_bonuses.items() if v
    ]
    return "  ·  ".join(parts)
