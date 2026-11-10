"""Admin web : le salon de chaque événement — les petits dans le général, le
salon des événements pour les gros (décision de l'auteur, 10/11/2026), sur
une copie du contenu."""

import json

import pytest

from app.infrastructure.events import event_config_loader as cfg
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)

FORGE = {"enabled": "on", "cadence_times": "1", "cadence_per_days": "3", "max_level": "10",
         "window_minutes": "5"}


@pytest.fixture
def events_copy(content, monkeypatch):
    monkeypatch.setattr(cfg, "CONTENT_PATH", content / "events.json")
    cfg.clear_cache()
    yield content / "events.json"
    cfg.clear_cache()


def test_les_pages_montrent_le_salon(client, events_copy):
    listing = client.get("/admin/events")
    assert listing.status_code == 200 and listing.text.count("📍 Salon général") == len(cfg.EVENT_TYPES)
    page = client.get("/admin/events/sacred_forge/edit")
    assert page.status_code == 200
    assert 'value="general" selected' in page.text and "Salon des événements" in page.text


def test_choisir_le_salon_d_un_evenement(client, events_copy):
    r = client.post("/admin/events/sacred_forge", data={**FORGE, "channel": "events"}, follow_redirects=False)
    assert r.status_code == 303
    assert json.loads(events_copy.read_text(encoding="utf-8"))["sacred_forge"]["channel"] == "events"
    assert cfg.channel_of("sacred_forge") == cfg.CHANNEL_EVENTS
    assert cfg.channel_of("chest") == cfg.CHANNEL_GENERAL
    # Une valeur inconnue, ou pas de champ, ne change rien.
    client.post("/admin/events/sacred_forge", data={**FORGE, "channel": "ailleurs"})
    client.post("/admin/events/sacred_forge", data=FORGE)
    assert cfg.channel_of("sacred_forge") == cfg.CHANNEL_EVENTS


def test_regler_la_duree_de_vie_du_coffre(client, events_copy):
    assert 'name="expire_after_minutes"' in client.get("/admin/events/chest/edit").text
    assert "disparaît après 24 h" in client.get("/admin/events").text
    form = {"enabled": "on", "cadence_times": "1", "cadence_per_days": "1", "level_scaling_pct": "2",
            "expire_after_minutes": "360", "loot_kind": "gold", "loot_gold": "100", "loot_weight": "10",
            "loot_item_code": "", "loot_quantity": "1"}
    assert client.post("/admin/events/chest", data=form, follow_redirects=False).status_code == 303
    assert cfg.chest_lifetime_minutes() == 360
    assert "disparaît après 6 h" in client.get("/admin/events").text
    client.post("/admin/events/chest", data={**form, "expire_after_minutes": "0"})
    assert cfg.chest_lifetime_minutes() == 5                     # plancher : jamais « tout de suite »
