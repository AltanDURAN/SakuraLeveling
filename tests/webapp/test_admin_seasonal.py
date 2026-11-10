"""Admin web : les fêtes (Monde › Fêtes) — calendrier de l'Avent, Noël,
objets et boutiques d'événement, Nouvel An, sur une copie du contenu. Tout
est vérifié avant d'écrire."""

import json

import pytest

from app.infrastructure.seasonal import seasonal_loader
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


@pytest.fixture
def seasonal_copy(content, monkeypatch):
    monkeypatch.setattr(seasonal_loader, "CONTENT_PATH", content / "seasonal_events.json")
    seasonal_loader.clear_cache()
    yield content / "seasonal_events.json"
    seasonal_loader.clear_cache()


def _saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_la_page_montre_les_fetes_et_ce_qui_vient(client, seasonal_copy):
    r = client.get("/admin/seasonal")
    assert r.status_code == 200
    for needle in ("Calendrier de l'Avent", "advent:2026-12-01", "new_year:2027-01-01", "seasonal-data",
                   "sucre_d_orge", "Boutiques d'événement"):
        assert needle in r.text, needle
    assert '"code": "arme_' not in r.text          # l'équipement n'est pas une récompense


def test_enregistrer_puis_refuser_un_contenu_casse(client, seasonal_copy):
    data = _saved(seasonal_copy)
    data["advent"]["start"] = "2026-11-21"                       # tester sur la bêta
    data["shops"][0]["offers"][0]["price"] = 99
    r = client.post("/admin/seasonal", data={"content": json.dumps(data)}, follow_redirects=False)
    assert r.status_code == 303
    saved = _saved(seasonal_copy)
    assert saved["advent"]["start"] == "2026-11-21" and saved["shops"][0]["offers"][0]["price"] == 99
    assert list(saved)[0] == "_comment"
    assert seasonal_loader.get_content().advent.start.isoformat() == "2026-11-21"

    broken = json.loads(json.dumps(saved))
    broken["christmas"]["claim_until"] = "2026-12-01"
    broken["advent"]["days"][0] = [{"kind": "item", "item": "surin_dentele", "qty": 1}]   # une arme
    r = client.post("/admin/seasonal", data={"content": json.dumps(broken)})
    assert r.status_code == 400
    assert "fin du cadeau est avant" in r.text and "objet inconnu « surin_dentele »" in r.text
    assert _saved(seasonal_copy) == saved                       # rien n'a été écrit
    assert client.post("/admin/seasonal", data={"content": "pas du json"}).status_code == 400
