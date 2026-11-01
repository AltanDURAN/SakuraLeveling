"""Admin web : Surveillance (01/11/2026) — toutes les pages s'affichent avec
des données, les seuils se règlent depuis le site, une alerte se met en
sourdine."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.application.monitoring import dataset
from app.infrastructure.monitoring import monitoring_loader
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)

PAGES = ("", "/activity", "/economy", "/combat", "/meta", "/progression", "/players", "/alerts", "/report",
         "/report?week=1", "?days=7&admins=1", "/players?days=90")


@pytest.fixture
def journal(client, content, monkeypatch):
    """Un peu de jeu : combats, or, niveaux, achats — et des points oubliés
    (une alerte « points à placer »)."""
    from app.application.monitoring.snapshots import take_snapshots
    from app.infrastructure.db.models.progression_model import PlayerProgressionModel
    from app.infrastructure.db.repositories.player_repository import PlayerRepository
    from app.infrastructure.db.session import get_db_session
    from app.infrastructure.encounters.farm_zone_loader import list_zones
    from app.infrastructure.monitoring.telemetry import record

    monkeypatch.setattr(monitoring_loader, "CONTENT_PATH", content / "monitoring.json")
    monitoring_loader.clear_cache()
    dataset.clear_cache()
    zone = str(list_zones()[0]["channel_id"])
    now = datetime.now(UTC).replace(tzinfo=None)
    with get_db_session() as s:
        pid = client.player_id
        repo = PlayerRepository(s)
        for k in range(12):
            at = now - timedelta(hours=3 * k)
            record(s, "interaction", player_id=pid, ref="profil", at=at)
            record(s, "combat", player_id=pid, zone=zone, ref="slime", gold=12, xp=8, qty=1, at=at,
                   data={"mobs": ["slime"], "res": "win" if k % 4 else "death", "n": 1, "turns": 9,
                         "enc": f"{zone}:{k}"})
        record(s, "flee", zone=zone, ref="gobelin", at=now - timedelta(hours=2))
        record(s, "shop_buy", player_id=pid, ref="parchemin_oubli", qty=1, gold=-150, at=now)
        record(s, "gear_drop", player_id=pid, ref="perle_de_gelee", data={"rarity": "epic"}, at=now)
        repo.add_gold(pid, 500, source="combat")
        repo.add_gold(pid, -150, source="boutique")
        repo.apply_progression(pid, 4, 0, 3)
        s.get(PlayerProgressionModel, pid).stat_points = 20
        s.commit()
        take_snapshots(s)
    yield pid
    dataset.clear_cache()
    monitoring_loader.clear_cache()


def test_toutes_les_pages_s_affichent(client, journal):
    for page in PAGES:
        r = client.get(f"/admin/monitoring{page}")
        assert r.status_code == 200, (page, r.text[:400])
    r = client.get(f"/admin/monitoring/players/{journal}")
    assert r.status_code == 200 and "Testeur" in r.text and "Parmi les autres" in r.text
    assert client.get("/admin/monitoring/players/987654").status_code == 404


def test_les_chiffres_arrivent_sur_les_pages(client, journal):
    combat = client.get("/admin/monitoring/combat").text
    assert "Slime" in combat and "Tous les monstres" in combat
    economy = client.get("/admin/monitoring/economy").text
    assert "Combats" in economy and "Sorn" in economy
    alerts = client.get("/admin/monitoring/alerts").text
    assert "points à placer" in alerts


def test_regler_les_seuils_depuis_le_site(client, journal, content):
    form = {"t_gold_rate_ratio": "4,5", "notify": "on", "notify_min_severity": "critique"}
    form.update({f"r_{code}": "on" for code in ("unexplained_gold", "gold_rate", "bot_like")})
    r = client.post("/admin/monitoring/alerts/settings", data=form, follow_redirects=False)
    assert r.status_code == 303
    saved = json.loads((content / "monitoring.json").read_text(encoding="utf-8"))
    assert saved["thresholds"]["gold_rate_ratio"] == 4.5
    assert saved["rules"]["gold_rate"] is True and saved["rules"]["unspent_points"] is False
    assert saved["notify"] == {"enabled": True, "min_severity": "critique"}
    settings = monitoring_loader.get_settings()
    assert settings.notifies("critique") and not settings.notifies("serieux")
    bad = client.post("/admin/monitoring/alerts/settings", data={"t_power_z": "beaucoup"})
    assert "doit être un nombre" in bad.text
    assert json.loads((content / "monitoring.json").read_text(encoding="utf-8"))["thresholds"]["power_z"] == 3.5


def test_mettre_une_alerte_en_sourdine(client, journal):
    from app.infrastructure.db.models.monitoring_model import MonitoringAlertModel
    from app.infrastructure.db.session import get_db_session

    r = client.post("/admin/monitoring/alerts/mute", data={"key": "unspent_points:all", "days": "7"},
                    follow_redirects=False)
    assert r.status_code == 303
    with get_db_session() as s:
        row = s.get(MonitoringAlertModel, "unspent_points:all")
        assert row is not None and row.muted_until is not None
    assert "en sourdine" in client.get("/admin/monitoring/alerts").text


def test_apres_un_lancement_de_saison_tout_repart_de_la(client, journal):
    """Le repère `season` : rien d'avant n'est compté, le bandeau l'annonce."""
    from app.infrastructure.db.session import get_db_session
    from app.infrastructure.monitoring.telemetry import record

    with get_db_session() as s:
        record(s, "season", ref="saison 1", qty=1)
        s.commit()
    dataset.clear_cache()
    page = client.get("/admin/monitoring").text
    assert "La <b>saison 1</b> a commencé" in page
    assert "Slime" not in client.get("/admin/monitoring/combat").text, "les combats d'avant la saison sont ignorés"
