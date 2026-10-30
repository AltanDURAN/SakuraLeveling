"""Admin web : rythme du jeu — délai entre deux monstres, fuite, temps pour
rejoindre, heures calmes, meutes, réglage par zone et raid (demande de
l'auteur, 27/10/2026), sur une copie du contenu."""

import json

import pytest

from app.infrastructure.encounters.farm_zone_loader import list_zones
from app.infrastructure.pacing import pacing_loader
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)

ZONES = {"respawn_min_minutes": "2", "respawn_max_minutes": "6,5", "flee_respawn_minutes": "10",
         "join_window_minutes": "4", "quiet_start_hour": "2", "quiet_end_hour": "8",
         "pack_chance_pct": "15", "pack_of_three_pct": "30"}


@pytest.fixture
def pacing_copy(content, monkeypatch):
    monkeypatch.setattr(pacing_loader, "CONTENT_PATH", content / "pacing.json")
    pacing_loader.clear_cache()
    yield content / "pacing.json"
    pacing_loader.clear_cache()


def _saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_la_page_s_affiche(client, pacing_copy):
    r = client.get("/admin/pacing")
    assert r.status_code == 200 and "Monstres de zone" in r.text and "Clairière sinistre" in r.text
    assert "20h50" in r.text and "21h" in r.text


def test_regler_les_zones(client, pacing_copy):
    assert client.post("/admin/pacing/zones", data=ZONES, follow_redirects=False).status_code == 303
    zones = pacing_loader.get_pacing().zones
    assert (zones.respawn_min_minutes, zones.respawn_max_minutes, zones.join_window_minutes) == (2, 6.5, 4)
    assert (zones.quiet_start_hour, zones.quiet_end_hour, zones.pack_chance_pct) == (2, 8, 15)
    bad = {**ZONES, "respawn_max_minutes": "1"}                     # max < min
    assert client.post("/admin/pacing/zones", data=bad).status_code == 400
    assert _saved(pacing_copy)["zones"]["respawn_max_minutes"] == 6.5   # rien n'a été écrit


def test_pause_et_delai_propre_a_une_zone(client, pacing_copy):
    channel = list_zones()[0]["channel_id"]
    r = client.post(f"/admin/pacing/zones/{channel}", data={"paused": "on", "respawn_min_minutes": "20",
                                                             "respawn_max_minutes": ""}, follow_redirects=False)
    assert r.status_code == 303
    own = pacing_loader.get_pacing().override(channel)
    assert own.paused and own.respawn_min_minutes == 20 and own.respawn_max_minutes is None
    # Tout vidé : la zone suit de nouveau le réglage général.
    client.post(f"/admin/pacing/zones/{channel}", data={"respawn_min_minutes": "", "respawn_max_minutes": ""})
    assert str(channel) not in _saved(pacing_copy)["zone_overrides"]
    assert client.post("/admin/pacing/zones/123", data={}).status_code == 404


def test_regler_le_raid(client, pacing_copy):
    form = {"spawn_weekday": "4", "spawn_hour": "18", "fight_time": "20:30", "registration_close_minutes": "15"}
    assert client.post("/admin/pacing/raid", data=form, follow_redirects=False).status_code == 303
    raid = pacing_loader.get_pacing().raid
    assert (raid.spawn_weekday, raid.spawn_hour, raid.fight_hour, raid.fight_minute) == (4, 18, 20, 30)
    assert client.post("/admin/pacing/raid", data={**form, "fight_time": "00:05"}).status_code == 400
    assert client.post("/admin/pacing/raid", data={**form, "fight_time": "vingt"}).status_code == 400
    assert _saved(pacing_copy)["raid"]["fight_minute"] == 30


def test_regler_les_evenements_lunaires(client, pacing_copy):
    r = client.get("/admin/pacing")
    assert "Lune de sang" in r.text and "Prochains événements" in r.text
    form = {}
    for code in ("pleine_lune", "lune_de_sang", "nouvelle_lune", "eclipse_lunaire", "eclipse_solaire"):
        form.update({f"{code}_enabled": "on", f"{code}_strength": "2", f"{code}_rewards": "3",
                     f"{code}_essences": "1", f"{code}_spawn_rate": "1", f"{code}_defense": "1",
                     f"{code}_element": "", f"{code}_element_weight": "1"})
    form.update(nouvelle_lune_element="tenebre", nouvelle_lune_element_weight="2")
    form.pop("nouvelle_lune_enabled")
    form["lune_de_sang_strength"] = "2,5"
    assert client.post("/admin/pacing/lunar", data=form, follow_redirects=False).status_code == 303
    lunar = pacing_loader.get_pacing().lunar
    assert lunar["lune_de_sang"].strength == 2.5 and not lunar["nouvelle_lune"].enabled
    assert (lunar["nouvelle_lune"].element, lunar["nouvelle_lune"].element_weight) == ("tenebre", 2)
    assert client.post("/admin/pacing/lunar", data={**form, "pleine_lune_element": "lave"}).status_code == 400
    assert client.post("/admin/pacing/lunar", data={**form, "pleine_lune_rewards": "0"}).status_code == 400
