"""Où paraissent les événements : les PETITS (coffre, petite fille, forge
sacrée) dans le salon général, le salon des événements est gardé pour les
gros (décision de l'auteur, 10/11/2026)."""

import json

import pytest

from app.bot.cogs import event_cog
from app.infrastructure.events import event_config_loader as cfg

GENERAL, EVENTS = 111, 222


@pytest.fixture
def channels(monkeypatch):
    monkeypatch.setattr(event_cog.settings, "rank_announce_channel_id", GENERAL)
    monkeypatch.setattr(event_cog.settings, "event_channel_id", EVENTS)


@pytest.fixture
def events_copy(tmp_path, monkeypatch):
    path = tmp_path / "events.json"
    path.write_text(cfg.CONTENT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(cfg, "CONTENT_PATH", path)
    cfg.clear_cache()
    yield path
    cfg.clear_cache()


class _Bot:
    def get_channel(self, channel_id):
        return f"salon {channel_id}"


def test_les_petits_evenements_paraissent_dans_le_general(channels):
    cfg.clear_cache()
    for kind in cfg.EVENT_TYPES:
        assert cfg.channel_of(kind) == cfg.CHANNEL_GENERAL, kind
        assert event_cog.event_channel_id(kind) == GENERAL
        assert event_cog._event_channel(_Bot(), kind) == f"salon {GENERAL}"


def test_un_gros_evenement_va_dans_le_salon_des_evenements(channels, events_copy):
    data = json.loads(events_copy.read_text(encoding="utf-8"))
    data["sacred_forge"]["channel"] = "events"
    data["chest"]["channel"] = "nulle_part"          # valeur inconnue : le général
    del data["little_girl"]["channel"]                # absent : le général
    events_copy.write_text(json.dumps(data), encoding="utf-8")
    cfg.clear_cache()
    assert event_cog.event_channel_id("sacred_forge") == EVENTS
    assert event_cog.event_channel_id("chest") == GENERAL
    assert event_cog.event_channel_id("little_girl") == GENERAL


def test_sans_salon_general_regle_on_retombe_sur_le_salon_des_evenements(channels, monkeypatch):
    monkeypatch.setattr(event_cog.settings, "rank_announce_channel_id", 0)
    cfg.clear_cache()
    assert event_cog.event_channel_id("chest") == EVENTS
