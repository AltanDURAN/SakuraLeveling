"""Zones prévues (C → S) : leur contenu existe, mais rien n'y spawne et leurs
familles restent cachées tant que la zone n'est pas ouverte."""

from app.infrastructure.encounters import farm_zone_loader as fz


def _data(monkeypatch, zones, planned):
    monkeypatch.setattr(fz, "_load", lambda: {
        "default_channel_id": 1, "zones": zones, "planned_zones": planned,
    })


def test_familles_des_zones_prevues_cachees(monkeypatch):
    _data(monkeypatch,
          [{"name": "Clairière", "channel_id": 1, "families": ["gobelin"]}],
          [{"name": "Faille", "channel_id": 0, "families": ["abyssal"]}])
    assert fz.unreleased_families() == {"abyssal"}
    # Une famille hors zone tomberait dans la zone de BASE : d'où le filtre.
    assert fz.get_spawn_channel_for_family("abyssal") == 1


def test_une_zone_ouverte_libere_sa_famille(monkeypatch):
    _data(monkeypatch,
          [{"name": "Faille", "channel_id": 9, "families": ["abyssal"]}],
          [{"name": "Faille", "channel_id": 0, "families": ["abyssal"]}])
    assert fz.unreleased_families() == set()


def test_le_contenu_reel_cache_les_quatre_familles():
    fz.clear_cache()
    assert {"primordial", "nocturne", "draconique", "abyssal"} <= fz.unreleased_families()
    released = {f for z in fz.list_zones() for f in z["families"]}
    assert {"gobelin", "mort-vivant", "demoniaque"} <= released
