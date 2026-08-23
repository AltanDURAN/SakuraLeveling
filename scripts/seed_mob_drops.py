"""Crée les objets de drop des monstres et remplit leurs tables de loot.

Principe (repris des deux mobs de référence, gobelin et gobelin assassin) :
chaque monstre lâche CE QU'IL PORTE À L'IMAGE, avec une rareté croissante :
    1. un matériau courant       ~20-25 %   (alimente le craft)
    2. une pièce qu'il porte     ~4-6 %     (équipable)
    3. sa signature              ~1-3 %     (la pièce convoitée)
S'y ajoute le drop commun de famille (dent_de_gobelin, fragment_d_me, gel_e,
c_ur_corrompu), géré à part par `family_drops.json`.

Anti-power-creep (cf. CLAUDE.md) : les bonus de stats restent MODESTES et
croissent avec la rareté ; les drops de monstre ne sont jamais achetables
(sell_price 0, buy_price null) — ils ne servent qu'au craft et à l'équipement.

Usage : .venv/bin/python -m scripts.seed_mob_drops [--write]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[1] / "app/infrastructure/content"

# --- Budget de stats par rareté : croissant, mais volontairement contenu. ----
# (référence existante : dagues_jumelles = rare = atk 10 + crit_dmg 20)
R = "resource"

# code, nom, catégorie, rareté, slot, stats, prix de vente
ITEMS: list[tuple] = [
    # ---------------- GOBELIN ----------------
    ("cuir_brut", "Cuir brut", R, "common", None, {}, 6),
    ("brassard_de_cuir", "Brassard de cuir", "bracelet", "uncommon", "bracelet",
     {"defense": 3, "speed": 1}, 0),
    ("baton_a_crane", "Bâton à crâne", "weapon", "rare", "main_droite",
     {"attack": 9, "mana_max": 20}, 0),
    ("fetiche_d_os", "Fétiche d'os", "necklace", "uncommon", "collier",
     {"crit_chance": 3, "mana_max": 10}, 0),
    ("gourde_de_chaman", "Gourde de chaman", R, "common", None, {}, 8),
    ("gourdin_de_tronc", "Gourdin de tronc", "weapon", "rare", "main_droite",
     {"attack": 14, "speed": -2}, 0),
    ("ceinturon_epais", "Ceinturon épais", "belt", "uncommon", "ceinture",
     {"max_hp": 25, "defense": 2}, 0),
    ("os_massif", "Os massif", R, "common", None, {}, 7),
    ("pierre_runique", "Pierre runique", R, "uncommon", None, {}, 18),
    ("collier_de_perles", "Collier de perles", "necklace", "uncommon", "collier",
     {"mana_max": 25, "mana_regeneration": 2}, 0),
    ("encre_rituelle", "Encre rituelle", R, "common", None, {}, 9),
    ("toile_de_dirigeable", "Toile de dirigeable", R, "common", None, {}, 10),
    ("grappin_rouille", "Grappin rouillé", R, "uncommon", None, {}, 16),
    ("masse_cloutee", "Masse cloutée", "weapon", "epic", "main_droite",
     {"attack": 22, "crit_damage": 15, "speed": -3}, 0),
    ("plaque_a_pointes", "Plaque à pointes", "chest", "rare", "plastron",
     {"defense": 12, "max_hp": 40}, 0),
    ("casque_a_cornes", "Casque à cornes", "helmet", "rare", "casque",
     {"defense": 8, "max_hp": 25, "crit_damage": 5}, 0),

    # ---------------- MORT-VIVANT ----------------
    ("os_poli", "Os poli", R, "common", None, {}, 6),
    ("dague_rouillee", "Dague rouillée", "weapon", "uncommon", "main_droite",
     {"attack": 6, "crit_chance": 2}, 0),
    ("poussiere_d_ossements", "Poussière d'ossements", R, "common", None, {}, 7),
    ("chair_putride", "Chair putride", R, "common", None, {}, 6),
    ("lambeau_de_vetement", "Lambeau de vêtement", R, "common", None, {}, 5),
    ("dent_gatee", "Dent gâtée", R, "common", None, {}, 6),
    ("chaine_spectrale", "Chaîne spectrale", "belt", "rare", "ceinture",
     {"defense": 7, "max_hp": 35, "dodge": 2}, 0),
    ("voile_ectoplasmique", "Voile ectoplasmique", "cape", "rare", "cape",
     {"dodge": 6, "speed": 3}, 0),
    ("boulet_hante", "Boulet hanté", "weapon", "rare", "main_droite",
     {"attack": 16, "speed": -4, "max_hp": 20}, 0),
    ("bandelette_maudite", "Bandelette maudite", R, "common", None, {}, 8),
    ("resine_d_embaumement", "Résine d'embaumement", R, "uncommon", None, {}, 17),
    ("griffe_noircie", "Griffe noircie", "weapon", "uncommon", "main_droite",
     {"attack": 7, "crit_chance": 4}, 0),
    ("eclat_de_pierre", "Éclat de pierre", R, "common", None, {}, 7),
    ("aile_de_pierre", "Aile de pierre", "cape", "rare", "cape",
     {"defense": 9, "max_hp": 30, "speed": -1}, 0),
    ("coeur_de_granit", "Cœur de granit", R, "rare", None, {}, 40),
    ("couronne_ternie", "Couronne ternie", "helmet", "epic", "casque",
     {"defense": 10, "mana_max": 40, "crit_damage": 12}, 0),
    ("orbe_maudit", "Orbe maudit", "shield", "epic", "main_gauche",
     {"mana_max": 50, "mana_regeneration": 3, "crit_damage": 15}, 0),
    ("grimoire_en_lambeaux", "Grimoire en lambeaux", "shield", "rare", "main_gauche",
     {"mana_max": 30, "mana_regeneration": 2}, 0),
    ("couronne_d_epines", "Couronne d'épines", "helmet", "epic", "casque",
     {"crit_chance": 7, "crit_damage": 18, "max_hp": -10}, 0),
    ("larme_spectrale", "Larme spectrale", R, "rare", None, {}, 45),
    ("echo_de_cri", "Écho de cri", R, "uncommon", None, {}, 20),

    # ---------------- SLIME ----------------
    ("noyau_de_slime", "Noyau de slime", R, "uncommon", None, {}, 15),

    # ---------------- DÉMONIAQUE ----------------
    ("trident_ebreche", "Trident ébréché", "weapon", "uncommon", "main_droite",
     {"attack": 8, "speed": 1}, 0),
    ("corne_naissante", "Corne naissante", R, "common", None, {}, 9),
    ("braise_infernale", "Braise infernale", R, "uncommon", None, {}, 19),
    ("corne_de_demon", "Corne de démon", R, "uncommon", None, {}, 22),
    ("lame_infernale", "Lame infernale", "weapon", "rare", "main_droite",
     {"attack": 15, "crit_damage": 12}, 0),
    ("ceinturon_cloute", "Ceinturon clouté", "belt", "rare", "ceinture",
     {"defense": 8, "max_hp": 30, "crit_chance": 2}, 0),
    ("espadon_dentele", "Espadon denté", "weapon", "epic", "main_droite",
     {"attack": 26, "crit_damage": 20, "defense": -4}, 0),
    ("plaque_rouillee", "Plaque rouillée", "chest", "rare", "plastron",
     {"defense": 13, "max_hp": 45, "speed": -2}, 0),
    ("croc_d_ogre", "Croc d'ogre", R, "uncommon", None, {}, 21),
    ("collier_a_pointes", "Collier à pointes", "necklace", "rare", "collier",
     {"attack": 6, "defense": 5}, 0),
    ("chaine_de_l_abime", "Chaîne de l'abîme", "belt", "rare", "ceinture",
     {"max_hp": 50, "defense": 6}, 0),
    ("croc_triple", "Croc triple", R, "rare", None, {}, 42),
    ("aile_de_cuir", "Aile de cuir", "cape", "rare", "cape",
     {"speed": 5, "dodge": 4}, 0),
    ("philtre_de_charme", "Philtre de charme", R, "rare", None, {}, 48),
    ("corset_de_soie_noire", "Corset de soie noire", "chest", "epic", "plastron",
     {"dodge": 8, "speed": 4, "crit_chance": 5}, 0),
    ("plume_noircie", "Plume noircie", R, "rare", None, {}, 44),
    ("couronne_dechue", "Couronne déchue", "helmet", "legendary", "casque",
     {"attack": 12, "defense": 12, "mana_max": 40, "crit_damage": 15}, 0),
    ("flamme_sacree", "Flamme sacrée", R, "epic", None, {}, 70),
    ("corne_d_archidemon", "Corne d'archidémon", R, "epic", None, {}, 75),
    ("lame_des_enfers", "Lame des enfers", "weapon", "legendary", "main_droite",
     {"attack": 34, "crit_chance": 6, "crit_damage": 25}, 0),
    ("sceau_de_corruption", "Sceau de corruption", "ring", "legendary", "bague",
     {"attack": 10, "max_hp": 60, "crit_damage": 20}, 0),
]

# mob → [(item, taux, qté min, qté max)]
LOOT: dict[str, list[tuple]] = {
    # -------- gobelin --------
    "gobelin": [("silex", 0.20, 1, 1), ("morceau_de_tissu", 0.18, 1, 2),
                ("diamant", 0.04, 1, 1)],
    "gobelin_combattant": [("cuir_brut", 0.22, 1, 2), ("brassard_de_cuir", 0.05, 1, 1),
                           ("silex", 0.15, 1, 2)],
    "gobelin_chaman": [("gourde_de_chaman", 0.20, 1, 1), ("fetiche_d_os", 0.05, 1, 1),
                       ("baton_a_crane", 0.02, 1, 1)],
    "gobelin_geant": [("os_massif", 0.22, 1, 2), ("ceinturon_epais", 0.05, 1, 1),
                      ("gourdin_de_tronc", 0.02, 1, 1)],
    "gobelin_runique": [("encre_rituelle", 0.20, 1, 2), ("pierre_runique", 0.10, 1, 1),
                        ("collier_de_perles", 0.04, 1, 1)],
    "gobelin_ballon": [("toile_de_dirigeable", 0.22, 1, 2), ("grappin_rouille", 0.10, 1, 1),
                       ("petite_bombe", 0.06, 1, 2)],
    "gobelin_assassin": [("morceau_de_tissu", 0.20, 1, 2), ("dagues_jumelles", 0.05, 1, 1),
                         ("cape_silencieuse", 0.01, 1, 1)],
    "gobelin_superieur": [("plaque_a_pointes", 0.05, 1, 1), ("casque_a_cornes", 0.04, 1, 1),
                          ("masse_cloutee", 0.015, 1, 1)],
    # -------- mort-vivant --------
    "squelette": [("os_poli", 0.22, 1, 2), ("poussiere_d_ossements", 0.18, 1, 2),
                  ("dague_rouillee", 0.05, 1, 1)],
    "zombie": [("chair_putride", 0.22, 1, 2), ("lambeau_de_vetement", 0.18, 1, 2),
               ("dent_gatee", 0.12, 1, 1)],
    "fantome": [("voile_ectoplasmique", 0.04, 1, 1), ("chaine_spectrale", 0.04, 1, 1),
                ("boulet_hante", 0.02, 1, 1)],
    "momie": [("bandelette_maudite", 0.22, 1, 2), ("resine_d_embaumement", 0.10, 1, 1),
              ("griffe_noircie", 0.05, 1, 1)],
    "gargouille": [("eclat_de_pierre", 0.22, 1, 2), ("aile_de_pierre", 0.04, 1, 1),
                   ("coeur_de_granit", 0.03, 1, 1)],
    "liche_maudite": [("grimoire_en_lambeaux", 0.05, 1, 1), ("orbe_maudit", 0.02, 1, 1),
                      ("couronne_ternie", 0.015, 1, 1)],
    "banshee": [("echo_de_cri", 0.18, 1, 1), ("larme_spectrale", 0.05, 1, 1),
                ("couronne_d_epines", 0.02, 1, 1)],
    # -------- slime --------
    "slime": [("potion_soin", 0.10, 1, 1), ("noyau_de_slime", 0.08, 1, 1),
              ("essence_de_vie", 0.04, 1, 1)],
    # -------- démoniaque --------
    "diablotin": [("corne_naissante", 0.22, 1, 2), ("braise_infernale", 0.10, 1, 1),
                  ("trident_ebreche", 0.05, 1, 1)],
    "demon_cornu": [("corne_de_demon", 0.20, 1, 2), ("ceinturon_cloute", 0.05, 1, 1),
                    ("lame_infernale", 0.025, 1, 1)],
    "ogre_demoniaque": [("croc_d_ogre", 0.20, 1, 2), ("plaque_rouillee", 0.05, 1, 1),
                        ("espadon_dentele", 0.015, 1, 1)],
    "cerbere": [("croc_triple", 0.12, 1, 2), ("collier_a_pointes", 0.05, 1, 1),
                ("chaine_de_l_abime", 0.03, 1, 1)],
    "succube": [("philtre_de_charme", 0.10, 1, 1), ("aile_de_cuir", 0.05, 1, 1),
                ("corset_de_soie_noire", 0.02, 1, 1)],
    "ange_dechu": [("plume_noircie", 0.15, 1, 2), ("flamme_sacree", 0.05, 1, 1),
                   ("couronne_dechue", 0.01, 1, 1)],
    "archidemon": [("corne_d_archidemon", 0.12, 1, 1), ("sceau_de_corruption", 0.02, 1, 1),
                   ("lame_des_enfers", 0.01, 1, 1)],
}


def build_item(code, name, category, rarity, slot, stats, sell) -> dict:
    return {
        "code": code, "name": name,
        "description": "",   # rempli côté admin / lore
        "category": category, "rarity": rarity,
        "stackable": slot is None, "max_stack": None,
        "sell_price": sell, "buy_price": None, "icon": None,
        "stat_bonuses": stats or None,
        "equipment_slot": slot, "requires_two_hands": False,
        "family": "",
    }


def main() -> None:
    write = "--write" in sys.argv
    items_path, mobs_path = CONTENT / "items.json", CONTENT / "mobs.json"
    items = json.loads(items_path.read_text(encoding="utf-8"))
    mobs = json.loads(mobs_path.read_text(encoding="utf-8"))
    known = {i["code"] for i in items}

    created = 0
    for row in ITEMS:
        if row[0] in known:
            continue
        items.append(build_item(*row))
        created += 1

    all_codes = {i["code"] for i in items}
    touched = 0
    for mob in mobs:
        entries = LOOT.get(mob["code"])
        if entries is None:
            continue
        missing = [c for c, *_ in entries if c not in all_codes]
        if missing:
            raise SystemExit(f"❌ {mob['code']} référence des items inconnus : {missing}")
        mob["loot_table"] = [
            {"item_code": c, "drop_rate": rate,
             "min_quantity": lo, "max_quantity": hi}
            for c, rate, lo, hi in entries
        ]
        touched += 1

    print(f"items créés : {created}  (total {len(items)})")
    print(f"tables de loot remplies : {touched} monstres")
    if write:
        items_path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        mobs_path.write_text(json.dumps(mobs, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
        print("✅ items.json et mobs.json mis à jour")
    else:
        print("(dry-run — relancer avec --write)")


if __name__ == "__main__":
    main()
