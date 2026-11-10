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
