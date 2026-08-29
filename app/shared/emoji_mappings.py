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


# Ré-export de la table canonique (app.shared.enums). Avant, ce module en
# gardait une COPIE : les deux ont divergé quand le mana est arrivé (🌀 valait
# esquive ici et régén mana là-bas). Une seule table désormais.
from app.shared.enums import STAT_EMOJIS  # noqa: F401  (ré-export public)

# Bonus de panoplie : même symbole que la stat correspondante. Dérivé de la
# table canonique — les panoplies peuvent donner du mana depuis V2.1.
BONUS_EMOJIS: dict[str, str] = {
    f"{key}_flat": emoji for key, emoji in STAT_EMOJIS.items()
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


def format_stat_bonuses_parts(stat_bonuses: dict | None) -> list[str]:
    """Liste des parts compactes (`+N emoji`) — utile pour le rendu
    multi-lignes (équipement card 1/2). Les valeurs négatives gardent
    leur signe natif (pas de double "+-")."""
    if not stat_bonuses:
        return []
    parts: list[str] = []
    for k, v in stat_bonuses.items():
        if not v:
            continue
        sign = "+" if v > 0 else ""
        parts.append(f"{sign}{v} {stat_emoji(k)}")
    return parts


def format_stat_bonuses_short(stat_bonuses: dict | None) -> str:
    """Bonus compact `+N {emoji} · -M {emoji}` — utilisé par les rendus
    où une seule ligne suffit (panoplie embed, etc.)."""
    return " · ".join(format_stat_bonuses_parts(stat_bonuses))
