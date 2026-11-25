"""Admin web : images d'objets en lot (Objets › Images en lot).

Chaque image s'envoie seule (le proxy du VPS limite une requête à 10 Mo), puis
UN seul commit pour tout le lot. Seule l'image change : jamais la fiche de
l'objet (le 03/11/2026, enregistrer les fiches pour changer leur image avait
effacé les stats en % de 11 pièces)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _same_origin(client):
    """Le back-office refuse une écriture sans origine connue (CSRF)."""
    client.headers.update({"origin": "http://localhost:8001"})


@pytest.fixture
def assets(tmp_path, monkeypatch):
    monkeypatch.setattr("webapp.admin.routers.items_router.ITEMS_ASSETS_DIR", tmp_path)

    def _no_item_write(*a, **k):
        raise AssertionError("les images en lot ne doivent jamais écrire la fiche de l'objet")

    monkeypatch.setattr("webapp.admin.content_sync.upsert_item_json", _no_item_write)
    monkeypatch.setattr("app.infrastructure.db.repositories.item_repository.ItemRepository.update_by_code",
                        _no_item_write)
    return tmp_path


def _png(size: int = 64, color=(200, 40, 40, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buf, "PNG")
    return buf.getvalue()


def _upload(client, code: str, data: bytes):
    return client.post(f"/admin/items/images/upload/{code}", files={"image": ("ChatGPT Image.png", data, "image/png")})


def test_la_page_montre_tous_les_objets(client):
    r = client.get("/admin/items/images")
    assert r.status_code == 200
    assert "lance_des_kobolds" in r.text and "potion_soin" in r.text


def test_une_image_est_ecrite_et_reduite_a_512_px(client, assets):
    r = _upload(client, "lance_des_kobolds", _png(1254))
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert r.json()["url"].startswith("/assets/items/lance_des_kobolds.png?v=")
    with Image.open(assets / "lance_des_kobolds.png") as img:
        assert img.size == (512, 512)


def test_une_image_sur_fond_blanc_est_detouree(client, assets):
    from PIL import ImageDraw

    image = Image.new("RGBA", (300, 300), (255, 255, 255, 255))
    ImageDraw.Draw(image).ellipse([60, 60, 240, 240], fill=(180, 30, 30, 255))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    assert _upload(client, "lance_des_kobolds", buffer.getvalue()).json()["ok"]
    with Image.open(assets / "lance_des_kobolds.png") as img:
        assert img.getpixel((5, 5))[3] == 0 and img.getpixel((150, 150))[3] == 255


def test_une_petite_image_garde_sa_taille_et_remplace_les_autres_formats(client, assets):
    (assets / "potion_soin.jpg").write_bytes(b"ancienne")
    assert _upload(client, "potion_soin", _png(300)).json()["ok"]
    assert not (assets / "potion_soin.jpg").exists()
    with Image.open(assets / "potion_soin.png") as img:
        assert img.size == (300, 300)


def test_objet_inconnu_ou_fichier_illisible(client, assets):
    r = _upload(client, "objet_qui_n_existe_pas", _png())
    assert r.status_code == 404 and not r.json()["ok"]
    r = _upload(client, "potion_soin", b"pas une image")
    assert r.status_code == 400 and "illisible" in r.json()["error"]
    assert not list(assets.iterdir())


def test_un_seul_commit_pour_tout_le_lot(client, assets, monkeypatch):
    calls = []
    monkeypatch.setattr("webapp.admin.git_sync.push_content", lambda paths, msg: calls.append((paths, msg)) or True)
    for code in ("potion_soin", "lance_des_kobolds"):
        assert _upload(client, code, _png()).json()["ok"]
    assert not calls                                    # rien n'est poussé pendant les envois
    r = client.post("/admin/items/images/push",
                    json={"codes": ["potion_soin", "lance_des_kobolds", "pas_envoyee", "../.env"]})
    assert r.json() == {"ok": True, "count": 2, "pushed": True}
    assert calls == [(["assets/items/lance_des_kobolds.png", "assets/items/potion_soin.png"],
                      "admin: 2 images d'objets")]


def test_rien_a_pousser(client, assets, monkeypatch):
    monkeypatch.setattr("webapp.admin.git_sync.push_content",
                        lambda *a: pytest.fail("aucun commit sans image"))
    assert client.post("/admin/items/images/push", json={"codes": []}).json()["count"] == 0




def test_tous_les_monstres_ont_le_meme_noir_et_blanc():
    """26/11/2026 (demande de l'auteur) : tous les dessins de monstres et de
    boss sont rangés en noir et blanc avec la même plage de tons
    (`prepare_mob_art`, appliqué à chaque dépôt sur le site)."""
    import json
    from pathlib import Path

    from PIL import Image, ImageStat

    from app.shared.image_tools import prepare_mob_art

    def drawing(fill) -> Image.Image:
        im = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
        im.paste(Image.new("RGBA", (40, 40), (*fill, 255)), (10, 10))
        im.paste(Image.new("RGBA", (40, 6), (0, 0, 0, 255)), (10, 10))
        return im

    def lum(im):
        return ImageStat.Stat(im.convert("L"), mask=im.getchannel("A")).mean[0]

    pale, dark, green = (prepare_mob_art(drawing(c)) for c in ((250, 250, 250), (60, 60, 60), (40, 220, 60)))
    assert abs(lum(pale) - lum(dark)) < 8
    assert ImageStat.Stat(green.convert("HSV").getchannel("S"), mask=green.getchannel("A")).mean[0] < 3
    assert pale.getchannel("A").getextrema()[0] == 0

    mobs = json.loads(Path("app/infrastructure/content/mobs.json").read_text(encoding="utf-8"))
    bosses = json.loads(Path("app/infrastructure/content/boss_definitions.json").read_text(encoding="utf-8"))
    names = {m["image_name"] for m in mobs if m.get("image_name")} | {b["image_name"] for b in bosses if b.get("image_name")}
    for name in names:
        path = Path("assets/mobs") / name
        if path.exists():
            im = Image.open(path).convert("RGBA")
            a = im.getchannel("A").point(lambda v: 255 if v > 128 else 0)
            assert ImageStat.Stat(im.convert("HSV").getchannel("S"), mask=a).mean[0] < 3, name
            hist = im.convert("L").histogram(mask=a)
            half, cum, median = sum(hist) / 2, 0, 0
            for median, count in enumerate(hist):
                cum += count
                if cum >= half:
                    break
            assert abs(median - 175) <= 10, (name, median)
