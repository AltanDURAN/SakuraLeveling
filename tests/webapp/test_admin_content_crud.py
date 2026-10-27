"""Admin web : création, modification et suppression du contenu JSON (titres,
quêtes, world boss) et préservation des données qu'un formulaire ne sait pas
éditer (effet d'un consommable, apparence d'un cosmétique).

Écrit AVANT le découpage de `content_router.py` (roadmap N6/N7, 26/10/2026)
pour servir de filet : tout se joue sur une COPIE du dossier de contenu."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)

CONTENT = Path(__file__).resolve().parents[2] / "app/infrastructure/content"


@pytest.fixture
def content(tmp_path, monkeypatch):
    """Copie du contenu ; tous les modules admin qui le lisent pointent dessus."""
    copy = tmp_path / "content"
    shutil.copytree(CONTENT, copy)
    for name, module in list(sys.modules.items()):
        if name.startswith("webapp.") and hasattr(module, "CONTENT_DIR"):
            monkeypatch.setattr(module, "CONTENT_DIR", copy)
    monkeypatch.setattr("webapp.admin.git_sync.push_content", lambda *a, **k: None)
    return copy


@pytest.fixture(autouse=True)
def _same_origin(client):
    """Le back-office refuse une écriture sans origine connue (CSRF)."""
    client.headers.update({"origin": "http://localhost:8001"})


def _load(content: Path, name: str):
    return json.loads((content / name).read_text(encoding="utf-8"))


def _codes(content: Path, name: str) -> set[str]:
    return {e["code"] for e in _load(content, name)}


def test_cycle_complet_d_un_titre(client, content):
    r = client.post("/admin/titles", data={
        "code": "titre_test", "name": "Titre de test", "description": "d", "icon": "🧪",
        "condition_type": "kills_total", "condition_value": "10", "effects": "dodge_flat::1",
    }, follow_redirects=False)
    assert r.status_code == 303 and "titre_test" in _codes(content, "titles.json")
    assert client.post("/admin/titles", data={"code": "titre_test", "name": "x"}).status_code == 400
    r = client.post("/admin/titles/titre_test", data={
        "name": "Titre renommé", "condition_type": "kills_total", "condition_value": "20", "effects": "",
    }, follow_redirects=False)
    assert r.status_code == 303
    title = next(t for t in _load(content, "titles.json") if t["code"] == "titre_test")
    assert title["name"] == "Titre renommé" and title["condition_value"] == 20
    assert client.post("/admin/titles/titre_test/delete", follow_redirects=False).status_code == 303
    assert "titre_test" not in _codes(content, "titles.json")


@pytest.mark.parametrize("scope,filename", [("daily", "daily_quests.json"), ("weekly", "weekly_quests.json")])
def test_cycle_complet_d_une_quete(client, content, scope, filename):
    r = client.post("/admin/quests", data={
        "scope": scope, "code": "quete_test", "name": "Quête test", "description": "Vaincre {n} {cible}",
        "tier": "easy", "objective_type": "kill_family", "target": "zone_family", "quantity": "4",
        "reward_gold": "10", "reward_xp": "20",
    }, follow_redirects=False)
    assert r.status_code == 303
    quest = next(q for q in _load(content, filename) if q["code"] == "quete_test")
    assert quest["target"] == "zone_family" and quest["quantity"] == 4
    r = client.post(f"/admin/quests/{scope}/quete_test", data={
        "name": "Quête modifiée", "tier": "hard", "objective_type": "kill_any", "quantity": "2.5",
    }, follow_redirects=False)
    assert r.status_code == 303
    quest = next(q for q in _load(content, filename) if q["code"] == "quete_test")
    assert quest["tier"] == "hard" and quest["quantity"] == 2.5
    assert client.post(f"/admin/quests/{scope}/quete_test/delete", follow_redirects=False).status_code == 303
    assert "quete_test" not in _codes(content, filename)


def test_editer_un_boss_garde_ce_que_le_formulaire_ne_montre_pas(client, content):
    before = next(b for b in _load(content, "boss_definitions.json") if b["code"] == "ancient_dragon")
    r = client.get("/admin/world-bosses/ancient_dragon/edit")
    assert r.status_code == 200 and "adds=" not in r.text
    r = client.post("/admin/world-bosses/ancient_dragon", data={
        "name": "Dragon renommé", "max_hp": str(before["max_hp"]),
        "modifiers": "damage_immunity_threshold=50, reflect_pct=20"}, follow_redirects=False)
    assert r.status_code == 303
    boss = next(b for b in _load(content, "boss_definitions.json") if b["code"] == "ancient_dragon")
    assert boss["name"] == "Dragon renommé" and boss["modifiers"]["damage_immunity_threshold"] == 50
    for key in ("element", "loot_table", "phases", "ultimate", "guards"):
        assert boss[key] == before[key]
    assert boss["modifiers"]["adds"] == before["modifiers"]["adds"]


def test_cycle_complet_d_un_world_boss(client, content):
    r = client.post("/admin/world-bosses", data={
        "code": "boss_test", "name": "Boss test", "max_hp": "5000", "attack": "40",
        "modifiers": "enrage_below_pct=20, crit_immunity=1",
    }, follow_redirects=False)
    assert r.status_code == 303
    boss = next(b for b in _load(content, "boss_definitions.json") if b["code"] == "boss_test")
    assert boss["max_hp"] == 5000 and boss["modifiers"]["enrage_below_pct"] == 20
    r = client.post("/admin/world-bosses/boss_test", data={"name": "Boss modifié", "max_hp": "6000"},
                    follow_redirects=False)
    assert r.status_code == 303
    boss = next(b for b in _load(content, "boss_definitions.json") if b["code"] == "boss_test")
    assert boss["name"] == "Boss modifié" and boss["max_hp"] == 6000
    assert client.post("/admin/world-bosses/boss_test/delete", follow_redirects=False).status_code == 303
    assert "boss_test" not in _codes(content, "boss_definitions.json")


def test_supprimer_un_contenu_inconnu_renvoie_404(client, content):
    assert client.post("/admin/titles/inconnu/delete").status_code == 404


@pytest.mark.parametrize("code,key", [("potion_mana", "effect"), ("cadre_or_royal", "cosmetic")])
def test_editer_un_objet_garde_son_effet_ou_son_apparence(client, content, code, key):
    """Le formulaire d'objet n'édite que des stats numériques : enregistrer une
    potion ou un cosmétique ne doit pas effacer ce qu'il fait."""
    before = next(i for i in _load(content, "items.json") if i["code"] == code)
    r = client.post(f"/admin/items/{code}", data={
        "name": before["name"] + " (édité)", "description": before["description"],
        "category": before["category"], "rarity": before["rarity"], "stackable": "on",
    }, follow_redirects=False)
    assert r.status_code == 303, r.text[:300]
    after = next(i for i in _load(content, "items.json") if i["code"] == code)
    assert after["name"].endswith("(édité)")
    assert after["stat_bonuses"][key] == before["stat_bonuses"][key]
