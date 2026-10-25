"""Texte joueur des effets d'une case de l'arbre (« +1 % d'attaque »).

Sert partout où un joueur découvre une case : menu « Investir » de `/arbre`,
infobulle de la page web. Une case sans description affiche ainsi quand même
ce qu'elle donne. Les effets particuliers (classes, passifs) ont leur texte
dans la description, écrite par l'auteur ; on n'y ajoute que la classe.
"""

from __future__ import annotations

from app.domain.services.combat_passives import FEATURES

#: type d'effet → gabarit ({v} = valeur au niveau considéré).
_TEMPLATES: dict[str, str] = {
    "atk_percent": "+{v} % d'attaque",
    "def_percent": "+{v} % de défense",
    "hp_max_percent": "+{v} % de PV max",
    "atk_flat": "+{v} attaque",
    "def_flat": "+{v} défense",
    "hp_max_flat": "+{v} PV max",
    "crit_chance_flat": "+{v} % de chances de critique",
    "crit_damage_flat": "+{v} % de dégâts critiques",
    "dodge_flat": "+{v} % d'esquive",
    "speed_flat": "+{v} vitesse",
    "hp_regeneration_flat": "+{v} régénération de PV / min",
    "mana_max_flat": "+{v} mana max",
    "mana_regeneration_flat": "+{v} régénération de mana / min",
    "gold_drop_percent": "+{v} % d'or gagné",
    "xp_drop_percent": "+{v} % d'XP gagnée",
    "drop_rate_multiplier": "+{v} % de chances de butin",
    "damage_dealt_percent": "+{v} % de dégâts infligés",
    "damage_taken_reduction_percent": "−{v} % de dégâts reçus",
    "armor_penetration_percent": "ignore {v} % de la défense ennemie",
    "lifesteal_percent": "se soigne de {v} % des dégâts infligés",
    "splash_damage_percent": "{v} % des dégâts aux ennemis adjacents",
    "taunt_chance_percent": "{v} % de chances de provoquer l'ennemi",
    "team_shield_percent": "bouclier de {v} % de ses PV max pour tout le groupe",
    "redirect_ally_damage_percent": "encaisse {v} % des coups portés à ses alliés",
    "heal_received_percent": "+{v} % de soins reçus",
    "heal_buff_percent": "ses soins donnent +{v} % ATK/DEF (une fois)",
    "heal_power_multiplier": "soins donnés ×{v}",
    "speed_per_ally": "+{v} vitesse par allié",
    "crit_chance_multiplier": "chances de critique ×{v}",
    "crit_damage_multiplier": "dégâts critiques ×{v}",
    "team_damage_percent": "aura : +{v} % de dégâts pour toute l'équipe",
    "defense_to_attack_percent": "ajoute {v} % de sa défense à son attaque",
}


def _fmt(value) -> str:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(f)) if f.is_integer() else f"{f:g}".replace(".", ",")


def effect_lines(node, level: int | None = None) -> list[str]:
    """Une ligne par effet, à `level` (défaut : niveau maximum)."""
    lvl = node.max_level if level is None else max(1, min(level, node.max_level))
    lines: list[str] = []
    for effect in node.effects:
        if not effect.values:
            continue
        value = effect.values[min(lvl, len(effect.values)) - 1]
        if effect.type in _TEMPLATES:
            lines.append(_TEMPLATES[effect.type].format(v=_fmt(value)))
        elif effect.type == "unlock_feature":
            lines.append(FEATURES.get(str(value), str(value)))
        elif effect.type == "grant_class":
            lines.append(f"accorde la classe {node.name}")
    return lines


def node_summary(node, level: int | None = None) -> str:
    """Description de l'auteur si elle existe, sinon le texte des effets."""
    if node.description:
        return node.description
    return " · ".join(effect_lines(node, level)) or "—"
