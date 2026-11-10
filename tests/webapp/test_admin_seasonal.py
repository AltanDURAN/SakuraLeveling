"""Admin web : les fêtes (Monde › Fêtes) — le calendrier de l'Avent tel que les
joueurs le verront (une case cliquée = son contenu), l'image EXACTE du bot,
les messages Discord en aperçu (construits par le code du bot), et un
enregistrement vérifié avant d'écrire. Sur une copie du contenu."""

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
    for needle in ("sz-data", "sz-items", "advent:2026-12-01", "new_year:2027-01-01", "Fêtes du Grand Cerisier",
                   "sucre_d_orge", "/assets/items/potion_soin.png", "Secret"):
        assert needle in r.text, needle
    assert '"code": "surin_dentele"' not in r.text          # l'équipement n'est pas une récompense


def test_enregistrer_puis_refuser_un_contenu_casse(client, seasonal_copy):
    data = _saved(seasonal_copy)
    data["advent"]["start"] = "2026-11-21"                       # tester sur la bêta
    data["shops"][0]["offers"][0]["price"] = 99
    r = client.post("/admin/seasonal/save", json=data)
    assert r.status_code == 200 and r.json() == {"ok": True}
    saved = _saved(seasonal_copy)
    assert saved["advent"]["start"] == "2026-11-21" and saved["shops"][0]["offers"][0]["price"] == 99
    assert list(saved)[0] == "_comment"
    assert seasonal_loader.get_content().advent.start.isoformat() == "2026-11-21"

    broken = json.loads(json.dumps(saved))
    broken["christmas"]["claim_until"] = "2026-12-01"
    broken["advent"]["days"][0] = [{"kind": "item", "item": "surin_dentele", "qty": 1}]   # une arme
    r = client.post("/admin/seasonal/save", json=broken)
    assert r.status_code == 400 and not r.json()["ok"]
    errors = " ".join(r.json()["errors"])
    assert "fin du cadeau est avant" in errors and "objet inconnu « surin_dentele »" in errors
    assert _saved(seasonal_copy) == saved                       # rien n'a été écrit
    # Le formulaire sans JavaScript reste possible.
    assert client.post("/admin/seasonal", data={"content": "pas du json"}).status_code == 400


def test_l_image_exacte_du_calendrier(client, seasonal_copy):
    advent = _saved(seasonal_copy)["advent"]
    r = client.post("/admin/seasonal/preview/advent.png", json={"advent": advent, "day": 14})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    bad = client.post("/admin/seasonal/preview/advent.png", json={"advent": {**advent, "days": []}, "day": 1})
    assert bad.status_code == 400


def test_les_messages_discord_en_apercu_sans_trahir_le_secret(client, seasonal_copy):
    data = _saved(seasonal_copy)
    data["new_year"]["title"] = "Bonne année de test !"          # pas encore enregistré : l'aperçu le suit
    seen = {}
    for kind, ref in (("gift", "naughty"), ("gift", "angel"), ("christmas", ""), ("advent", ""),
                      ("drop", "sucres_d_orge"), ("shop", "atelier_lutins"), ("new_year", ""), ("panel", "")):
        r = client.post("/admin/seasonal/preview/embed",
                        json={"content": data, "kind": kind, "ref": ref, "level": 10, "date": "2026-12-20"})
        out = r.json()
        assert r.status_code == 200 and "embeds" in out, (kind, out)
        seen[(kind, ref)] = json.dumps(out, ensure_ascii=False)
    assert "Bonne année de test" in seen[("new_year", "")] and '"content": "@everyone"' in seen[("new_year", "")]
    assert "Aurélia" in seen[("new_year", "")]
    assert "maigre" in seen[("gift", "naughty")] and "déborde" in seen[("gift", "angel")]
    assert "case **20**" in seen[("panel", "")]
    for text in seen.values():
        assert "petite fille" not in text.lower()
    nothing = client.post("/admin/seasonal/preview/embed", json={"content": {}, "kind": "gift"}).json()
    assert "error" in nothing
