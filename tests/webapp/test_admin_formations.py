"""Admin web : formations des meutes (Scènes › Formations) — pages, aperçu
réel, enregistrement et retour au défaut, sur une copie du contenu."""

import json

from app.infrastructure.encounters import farm_zone_loader, mob_formation_loader
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


def _zone_key() -> str:
    return str(next(z["channel_id"] for z in farm_zone_loader.list_zones() if z.get("channel_id")))


def test_pages_et_apercu(client, content):
    key = _zone_key()
    assert client.get("/admin/scenes/formations").status_code == 200
    assert client.get(f"/admin/scenes/formations/{key}/3").status_code == 200
    r = client.get(f"/admin/scenes/formations/{key}/3/preview.png?x0=-0.3&y0=0&s0=0.8")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get(f"/admin/scenes/formations/{key}/7").status_code == 404


def test_enregistrer_puis_retablir(client, content, monkeypatch):
    monkeypatch.setattr(mob_formation_loader, "CONTENT_PATH", content / "mob_formations.json")
    mob_formation_loader.reload_cache()
    key = _zone_key()
    form = {"x0": "-0.2", "y0": "0", "s0": "0.9", "x1": "0.25", "y1": "-0.04", "s1": "0.7"}
    assert client.post(f"/admin/scenes/formations/{key}/2", data=form,
                       follow_redirects=False).status_code == 303
    saved = json.loads((content / "mob_formations.json").read_text(encoding="utf-8"))
    assert saved["formations"][key]["2"][1] == {"x": 0.25, "y": -0.04, "scale": 0.7}
    assert mob_formation_loader.get_formation(key, 2)[1]["x"] == 0.25
    client.post(f"/admin/scenes/formations/{key}/2", data={"reset": "1"}, follow_redirects=False)
    assert mob_formation_loader.get_formation(key, 2) == mob_formation_loader.DEFAULT_FORMATIONS[2]
