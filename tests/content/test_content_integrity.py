"""Cohérence du contenu JSON : chaque référence pointe vers quelque chose qui
existe, et les règles de l'équipement v2 sont tenues (une pièce par monstre,
un passif par pièce). Un oubli ici casse un drop ou une fusion en silence."""

import json
from pathlib import Path

from app.domain.services.gear_passives import PASSIVES
from app.shared.enums import EQUIPABLE_CATEGORIES

C = Path(__file__).resolve().parents[2] / "app/infrastructure/content"


def load(name):
    return json.loads((C / name).read_text(encoding="utf-8"))


ITEMS = {i["code"]: i for i in load("items.json")}
MOBS = load("mobs.json")
FAMILY_DROPS = load("family_drops.json")
ZONES = load("farm_zones.json")


def test_chaque_monstre_porte_une_piece_unique_et_existante():
    worn = {}
    for m in MOBS:
        code = m.get("gear_item_code")
        assert code, f"{m['code']} ne porte aucune pièce"
        assert ITEMS.get(code, {}).get("category") in EQUIPABLE_CATEGORIES, (m["code"], code)
        assert code not in worn, f"{code} porté par {worn.get(code)} et {m['code']}"
        worn[code] = m["code"]


def test_chaque_passif_existe_et_n_est_porte_qu_une_fois():
    seen = {}
    for code, item in ITEMS.items():
        passive = item.get("passive") or ""
        if not passive:
            continue
        assert passive in PASSIVES, (code, passive)
        assert passive not in seen, f"{passive} sur {seen.get(passive)} et {code}"
        seen[passive] = code


def test_chaque_famille_a_son_materiau_et_sa_zone():
    families = {m["family"] for m in MOBS}
    zoned = {f for z in ZONES["zones"] + ZONES.get("planned_zones", []) for f in z["families"]}
    for fam in families:
        assert fam in FAMILY_DROPS, f"famille {fam} sans drop de famille (fusion impossible)"
        assert FAMILY_DROPS[fam]["item_code"] in ITEMS
        assert fam in zoned, f"famille {fam} dans aucune zone (elle tomberait dans la zone de base)"
        members = {m["code"] for m in MOBS if m["family"] == fam}
        assert set(FAMILY_DROPS[fam]["mobs"]) <= members


def test_les_butins_et_recompenses_pointent_vers_des_objets():
    refs = [(m["code"], e["item_code"]) for m in MOBS for e in m.get("loot_table") or []]
    refs += [("shop", s["item_code"]) for s in load("shop_items.json")]
    for loot in load("events.json").get("chest", {}).get("loot", []):
        if loot.get("item_code"):
            refs.append(("coffre", loot["item_code"]))
    for name in ("daily_quests.json", "weekly_quests.json"):
        for q in load(name):
            refs += [(q["code"], code) for code, _ in q.get("reward_items") or []]
    missing = [r for r in refs if r[1] not in ITEMS]
    assert missing == []


def test_les_titres_visent_des_monstres_et_familles_existants():
    mob_codes = {m["code"] for m in MOBS}
    families = {m["family"] for m in MOBS}
    for t in load("titles.json"):
        if t.get("condition_type") == "kills_mob":
            assert t["condition_target"] in mob_codes, t["code"]
        if t.get("condition_type") == "kills_family":
            assert t["condition_target"] in families, t["code"]
