"""Capacités spéciales propres à certains monstres (identifiées par code).

Deux usages :
  • `get_mob_abilities(code)` → config lue par `PartyCombatService` (hooks combat).
  • `get_mob_ability_summary(code)` → résumé FR affiché dans le bestiaire / l'admin.

Ajouter une capacité = une entrée dans MOB_ABILITIES (+ un résumé) et, si la
mécanique est inédite, un hook côté PartyCombatService. Le combat lit un simple
dict passé en paramètre (il n'importe pas ce module).
"""

from __future__ import annotations

# Config machine (params lus par le moteur de combat).
MOB_ABILITIES: dict[str, dict] = {
    "gobelin_runique":   {"death_explosion": {"attack_multiplier": 3}},
    "gobelin_assassin":  {"opening_assassinate": {}},
    "succube":           {"charm": {}},
    "ange_dechu":        {"revive": {"atk_pct": 100, "def_pct": 100}},
    "cerbere":           {"multi_hit": {"hits": 3}},
    # Furie : à ≤75% PV +50% atk/déf, ≤50% +100%, ≤25% +300% (le palier le + bas gagne).
    "archidemon":        {"enrage": {"tiers": [[75, 50], [50, 100], [25, 300]]}},
    "gobelin_superieur": {"shield": {"reset_on_kill": True}},   # bouclier = 100% PV max
    "gobelin_geant":     {"aoe": {}, "stun": {"chance": 40}},
    "banshee":           {"aoe": {}, "stun": {"chance": 50}},
    "fantome":           {"first_hit_dodge": {}},
    "gargouille":        {"lifesteal": {"pct": 20}},
    "liche_maudite":     {"alternating": {"single_multiplier": 3}},
    "momie":             {"slow": {"pct": 50}},
    "gobelin_chaman":    {"heal_once_below": {"hp_pct": 50}},
}

# Résumé lisible (bestiaire / badges admin).
MOB_ABILITY_SUMMARY: dict[str, str] = {
    "gobelin_runique":   "Explosion mortelle : à sa mort, inflige 3× son attaque à chaque joueur (esquivable).",
    "gobelin_assassin":  "Assassinat : frappe d'ouverture prioritaire, toujours critique sur le plus faible, enchaîne sur chaque kill (×2, ×3…).",
    "succube":           "Charme : retourne le joueur le plus puissant contre son équipe ; intouchable tant qu'il vit.",
    "ange_dechu":        "Résurrection : revient une fois à la vie à 100% PV avec +100% d'attaque et de défense.",
    "cerbere":           "Trois têtes : chaque attaque frappe 3 fois.",
    "archidemon":        "Furie : plus ses PV sont bas, plus il frappe fort (+50% / +100% / +300% atk & déf à 75% / 50% / 25% PV).",
    "gobelin_superieur": "Bouclier : démarre avec un bouclier de 100% des PV max ; il se recharge à chaque joueur tué.",
    "gobelin_geant":     "Frappe de zone : touche tous les joueurs et peut étourdir la cible (40%).",
    "banshee":           "Cri de zone : touche tous les joueurs et peut étourdir la cible (50%).",
    "fantome":           "Insaisissable : esquive garantie la toute première attaque de chaque joueur.",
    "gargouille":        "Vol de vie : récupère 20% des dégâts qu'elle inflige (sans dépasser ses PV max).",
    "liche_maudite":     "Sorts alternés : alterne zone et mono-cible ; l'attaque mono-cible fait ×3 dégâts.",
    "momie":             "Malédiction lente : ses coups ralentissent le joueur de 50% (non cumulable en %, cumulable en durée).",
    "gobelin_chaman":    "Incantation : la première fois qu'il passe sous 50% PV, il se soigne à 100% au tour suivant.",
}


def get_mob_abilities(mob_code: str | None) -> dict:
    """Capacités spéciales du monstre (dict vide si aucune)."""
    return dict(MOB_ABILITIES.get(mob_code or "", {}))


def get_mob_ability_summary(mob_code: str | None) -> str | None:
    """Résumé FR de la spécialité du monstre, ou None s'il n'en a pas."""
    return MOB_ABILITY_SUMMARY.get(mob_code or "")


def has_special(mob_code: str | None) -> bool:
    return bool(MOB_ABILITIES.get(mob_code or ""))
