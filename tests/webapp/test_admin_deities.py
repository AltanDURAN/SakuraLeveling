"""Monde › Divinités : images des divinités et du Grand Cerisier (28/11/2026)."""

import io

from PIL import Image

from app.infrastructure.cards import card_loader
from tests.webapp.test_admin_cards import cards  # noqa: F401  (fixture)
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (900, 1260), (200, 170, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_la_page_montre_les_divinites_et_le_grand_cerisier(client, cards):
    html = client.get("/admin/divinites").text
    for name in ("Aurélia", "Kaïros", "Lysia", "Sylve", "Éona", "Morrigane", "Thalos", "Grand Cerisier"):
        assert name in html
    assert "/admin/divinites/aurelia/image" in html and "ébauche" in html
    assert client.get("/admin/divinites/aurelia/image").status_code == 200
    assert "face.png" not in html  # la divinité, pas sa carte


def test_deposer_l_image_d_une_divinite(client, cards, _same_origin, monkeypatch):
    monkeypatch.setattr("webapp.admin.git_sync.push_content", lambda *a, **k: False)
    card = card_loader.get_card("sylve")
    r = client.post("/admin/divinites/sylve/carte", files={"image": ("sylve.png", _png(), "image/png")},
                    follow_redirects=False)
    assert r.status_code == 303 and "ok=sylve" in r.headers["location"]
    assert card_loader.own_art_path(card).is_file() and card_loader.art_origin(card) == "carte"
    html = client.get("/admin/divinites").text
    assert "la tienne" in html
    assert client.get("/admin/divinites/sylve/image").content[:4] == b"\x89PNG"
    assert client.get("/admin/divinites/slime/image").status_code == 404
    assert client.post("/admin/divinites/slime/carte", files={"image": ("a.png", _png(), "image/png")}).status_code == 404
