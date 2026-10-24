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
    "ange_dechu":        {"revive": {"atk_pct": 100, "def_pct": 0}},
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
    "ogre_demoniaque":   {"bleed": {"pct": 10, "turns": 3, "max_stacks": 3}},
    "gobelin_ballon":    {"aoe": {}, "chain_replicate": {"chance": 20}},
    "slime":             {"absorb": {"chance": 10, "stat_pct": 50}},
    # --- Zones C → S (prévues, pas encore ouvertes)
    "serpent_des_racines": {"poison": {"pct_max_hp": 3, "turns": 4}},
    "ours_colosse": {"armor_break": {"pct": 10, "max_pct": 30}},
    "golem_de_mousse": {"regen": {"pct": 2}},
    "aigle_tempete": {"aoe": {}, "stun": {"chance": 30}},
    "loup_garou": {"enrage": {"tiers": [[50, 25], [25, 50]]}},
    "sorciere_de_sang": {"summon": {"atk_pct": 30, "every": 3, "max": 2}},
    "chevalier_de_l_eclipse": {"reflect": {"pct": 15}},
    "vampire_noble": {"lifesteal": {"pct": 25}},
    "comtesse_ecarlate": {"first_hit_dodge": {}, "bleed": {"pct": 10, "turns": 3, "max_stacks": 3}},
    "drake_de_braise": {"poison": {"pct_max_hp": 4, "turns": 3}},
    "wyverne": {"multi_hit": {"hits": 2}},
    "dragon_de_givre": {"aoe": {}, "stun": {"chance": 25}},
    "gardien_draconique": {"reflect": {"pct": 10}, "armor_break": {"pct": 5, "max_pct": 20}},
    "dragon_ancien": {"aoe": {}, "enrage": {"tiers": [[75, 30], [50, 60], [25, 100]]}},
    "devoreur": {"lifesteal": {"pct": 20}},
    "heraut_du_vide": {"summon": {"atk_pct": 35, "every": 3, "max": 3}},
    "kraken_astral": {"multi_hit": {"hits": 3}, "slow": {"pct": 50}},
    "seraphin_brise": {"revive": {"atk_pct": 50, "def_pct": 0}},
    "avatar_du_neant": {"alternating": {"single_multiplier": 3}, "armor_break": {"pct": 10, "max_pct": 30}},
}

# Résumé lisible (bestiaire / badges admin).
MOB_ABILITY_SUMMARY: dict[str, str] = {
    "gobelin_runique":   "Explosion mortelle : à sa mort, inflige 3× son attaque à chaque joueur (esquivable).",
    "gobelin_assassin":  "Assassinat : frappe d'ouverture prioritaire, toujours critique sur le plus faible, enchaîne sur chaque kill (×2, ×3…).",
    "succube":           "Charme : retourne le joueur le plus puissant contre son équipe ; intouchable tant qu'il vit.",
    "ange_dechu":        "Résurrection : revient une fois à la vie à 100% PV avec +100% d'attaque.",
    "cerbere":           "Trois têtes : chaque attaque frappe 3 fois.",
    "archidemon":        "Furie : plus ses PV sont bas, plus il frappe fort (+50% / +100% / +300% d'attaque à 75% / 50% / 25% PV).",
    "gobelin_superieur": "Bouclier : démarre avec un bouclier de 100% des PV max ; il se recharge à chaque joueur tué.",
    "gobelin_geant":     "Frappe de zone : touche tous les joueurs et peut étourdir la cible (40%).",
    "banshee":           "Cri de zone : touche tous les joueurs et peut étourdir la cible (50%).",
    "fantome":           "Insaisissable : esquive garantie la toute première attaque de chaque joueur.",
    "gargouille":        "Vol de vie : récupère 20% des dégâts qu'elle inflige (sans dépasser ses PV max).",
    "liche_maudite":     "Sorts alternés : alterne zone et mono-cible ; l'attaque mono-cible fait ×3 dégâts.",
    "momie":             "Malédiction lente : ses coups ralentissent le joueur de 50% (non cumulable en %, cumulable en durée).",
    "gobelin_chaman":    "Incantation : la première fois qu'il passe sous 50% PV, il se soigne à 100% au tour suivant.",
    "ogre_demoniaque":   "Saignement : ses coups font saigner (10% des dégâts par tour pendant 3 tours, cumulable jusqu'à 3 fois).",
    "gobelin_ballon":    "Explosion en chaîne : frappe tous les joueurs et a 20% de se répliquer (en cascade, chaque réplique peut relancer).",
    "slime":             "Absorption : 10% au début d'engloutir tous les joueurs sauf le plus fort, se renforçant de 50% de leurs statistiques.",
    # --- Zones C → S
    "serpent_des_racines": "Venin : ses coups empoisonnent (3 % des PV max par tour pendant 4 tours, ignore la défense, non cumulable).",
    "ours_colosse": "Brise-armure : chaque coup réduit la défense de la cible de 10 % pour le combat (max 30 %).",
    "golem_de_mousse": "Régénération : récupère 2 % de ses PV max à chaque action.",
    "aigle_tempete": "Frappe de zone : touche tous les joueurs et peut étourdir (30 %).",
    "loup_garou": "Furie : plus ses PV baissent, plus il frappe fort (+25 % sous 50 % / +50 % sous 25 %).",
    "sorciere_de_sang": "Invocation : appelle un familier tous les 3 tours (max 2), chacun frappe à 30 % de son attaque.",
    "chevalier_de_l_eclipse": "Riposte d'ombre : renvoie 15 % des dégâts reçus à l'attaquant.",
    "vampire_noble": "Vol de vie : récupère 25 % des dégâts qu'il inflige.",
    "comtesse_ecarlate": "Danse écarlate : esquive la première attaque de chaque joueur, et ses coups font saigner (10 % des dégâts par tour pendant 3 tours, jusqu'à 3 fois).",
    "drake_de_braise": "Brûlure : ses coups brûlent (4 % des PV max par tour pendant 3 tours, ignore la défense, non cumulable).",
    "wyverne": "Assaut : chaque attaque frappe 2 fois.",
    "dragon_de_givre": "Frappe de zone : touche tous les joueurs et peut étourdir (25 %).",
    "gardien_draconique": "Écailles tranchantes : renvoie 10 % des dégâts reçus, et chaque coup réduit la défense de la cible de 5 % (max 20 %).",
    "dragon_ancien": "Frappe de zone : touche tous les joueurs. Furie : plus ses PV baissent, plus il frappe fort (+30 % sous 75 % / +60 % sous 50 % / +100 % sous 25 %).",
    "devoreur": "Vol de vie : récupère 20 % des dégâts qu'il inflige.",
    "heraut_du_vide": "Invocation : appelle un familier tous les 3 tours (max 3), chacun frappe à 35 % de son attaque.",
    "kraken_astral": "Assaut : chaque attaque frappe 3 fois et ralentit sa cible de 50 %.",
    "seraphin_brise": "Renaissance : revient une fois à la vie à 100 % PV, avec +50 % d'attaque.",
    "avatar_du_neant": "Sorts alternés : alterne zone et mono-cible ; la frappe mono-cible fait ×3. Brise-armure : chaque coup réduit la défense de la cible de 10 % pour le combat (max 30 %).",
}


def get_mob_abilities(mob_code: str | None) -> dict:
    """Capacités spéciales du monstre (dict vide si aucune)."""
    return dict(MOB_ABILITIES.get(mob_code or "", {}))


def get_mob_ability_summary(mob_code: str | None) -> str | None:
    """Résumé FR de la spécialité du monstre, ou None s'il n'en a pas."""
    return MOB_ABILITY_SUMMARY.get(mob_code or "")


def has_special(mob_code: str | None) -> bool:
    return bool(MOB_ABILITIES.get(mob_code or ""))
