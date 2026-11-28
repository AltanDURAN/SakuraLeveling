"""Portraits des personnages déposés depuis le site (28/11/2026)."""

import io

import pytest
from PIL import Image

from tests.webapp.test_admin_content_crud import _same_origin  # noqa: F401  (fixture)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


@pytest.fixture
def npcs_dir(tmp_path, monkeypatch):
    folder = tmp_path / "npcs"
    folder.mkdir()
    monkeypatch.setattr("webapp.admin.routers.npcs_router.NPCS_ASSETS_DIR", folder)
    monkeypatch.setattr("webapp.admin.routers.npcs_router.git_sync.push_content", lambda *a, **k: False)
    return folder


def _png(size=(1600, 1600)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (120, 60, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_la_page_montre_les_cinq_personnages(client, npcs_dir):
    html = client.get("/admin/npcs").text
    for name in ("Hana", "Borak", "Elna", "Sorn", "Ysaline"):
        assert name in html


def test_un_portrait_depose_remplace_le_fichier_reduit_a_1024(client, npcs_dir, _same_origin):
    r = client.post("/admin/npcs/hana", files={"image": ("portrait.png", _png(), "image/png")},
                    follow_redirects=False)
    assert r.status_code == 303 and "ok=hana" in r.headers["location"]
    with Image.open(npcs_dir / "hana.png") as saved:
        assert saved.format == "PNG" and max(saved.size) == 1024


def test_un_fichier_qui_n_est_pas_une_image_est_refuse(client, npcs_dir, _same_origin):
    r = client.post("/admin/npcs/borak", files={"image": ("note.png", b"pas une image", "image/png")},
                    follow_redirects=False)
    assert r.status_code == 303 and "erreur=" in r.headers["location"]
    assert not (npcs_dir / "forgeron.png").exists()
    assert client.post("/admin/npcs/inconnu", files={"image": ("a.png", _png(), "image/png")}).status_code == 404
