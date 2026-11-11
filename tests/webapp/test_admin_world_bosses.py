"""Admin web : les world boss en images (11/11/2026, demande de l'auteur :
« que je dépose les images des boss »). La galerie montre chaque boss tel que
le bot le dessine (vidéo de l'assaut, bannière du raid) ; on y dépose son
image (détourée si fond blanc, recadrée, rangée en boss_<code>.png) et son
arène. Sur une copie du contenu et des dossiers d'images."""

from __future__ import annotations

import io
import json
import shutil

import pytest
from PIL import Image, ImageDraw

from app.bot.rendering import boss_fight_video as bfv
from app.bot.rendering import fight_scene
from app.shared.paths import LANDSCAPES_ASSETS_DIR
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


def _bosses(content):
    return {b["code"]: b for b in json.loads((content / "boss_definitions.json").read_text(encoding="utf-8"))}


def _png(size=(800, 900), white=True, circle=True) -> bytes:
    image = Image.new("RGBA", size, (255, 255, 255, 255) if white else (40, 90, 60, 255))
    if circle:
        ImageDraw.Draw(image).ellipse((200, 200, 600, 700), fill=(200, 30, 40, 255), outline=(10, 10, 10, 255), width=6)
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def assets(tmp_path, monkeypatch):
    """Dossiers d'images jetables : le site y range, le rendu du bot y lit."""
    mobs, landscapes = tmp_path / "mobs", tmp_path / "landscapes"
    mobs.mkdir()
    landscapes.mkdir()
    shutil.copy(LANDSCAPES_ASSETS_DIR / "berceau_cataclysmique.png", landscapes)
    monkeypatch.setattr(fight_scene, "MOBS_ASSETS_DIR", mobs)
    monkeypatch.setattr(bfv, "LANDSCAPES_ASSETS_DIR", landscapes)
    synced = []
    monkeypatch.setattr("webapp.admin.routers.world_bosses_router._sync_instances",
                        lambda code, name: synced.append((code, name)))
    return mobs, landscapes, synced


def test_la_galerie_montre_chaque_boss_et_d_ou_vient_son_image(client, content):
    r = client.get("/admin/world-bosses")
    assert r.status_code == 200
    data = json.loads(r.text.split('id="wb-data">')[1].split("</script>")[0])
    by_code = {b["code"]: b for b in data["bosses"]}
    assert set(by_code) == set(_bosses(content))
    titan = by_code["slime_titan"]
    # En attendant la sienne, le Titan porte l'image du slime.
    assert titan["image_origin"] == "empruntee" and titan["borrowed_from"]
    assert titan["image_url"].startswith("/assets/mobs/slime.png")
    assert titan["card_url"] == "/admin/cards/slime_titan" and titan["guards"]
    assert [b["level"] for b in data["bosses"]] == sorted(b["level"] for b in data["bosses"])


def test_les_apercus_sont_dessines_par_le_code_du_bot(client, content):
    scene = client.get("/admin/world-bosses/slime_titan/scene.jpg")
    assert scene.status_code == 200 and scene.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(scene.content)).size == (fight_scene.FRAME_W, fight_scene.FRAME_H)
    banner = client.get("/admin/world-bosses/slime_titan/banner.png")
    assert banner.status_code == 200 and banner.content[:4] == b"\x89PNG"
    assert client.get("/admin/world-bosses/inconnu/scene.jpg").status_code == 404


def test_deposer_l_image_d_un_boss(client, content, assets):
    mobs, _, synced = assets
    r = client.post("/admin/world-bosses/slime_titan/image", data={"slot": "boss"},
                    files={"image": ("Titan Visqueux.png", _png(), "image/png")})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert "Fond blanc retiré." in r.json()["notes"]
    saved = Image.open(mobs / "boss_slime_titan.png")
    assert saved.mode == "RGBA" and saved.getpixel((0, 0))[3] == 0          # détourée…
    assert saved.size[0] < 800 and saved.size[1] < 900                       # … et recadrée sur le boss
    assert _bosses(content)["slime_titan"]["image_name"] == "boss_slime_titan.png"
    assert synced == [("slime_titan", "boss_slime_titan.png")]               # le boss en cours suit
    state = r.json()["boss"]
    assert state["image_origin"] == "propre" and state["image_url"].startswith("/assets/mobs/boss_slime_titan.png")
    # Une image sans transparence est rangée, mais on prévient.
    r = client.post("/admin/world-bosses/slime_titan/image", data={"slot": "boss"},
                    files={"image": ("photo.png", _png(white=False), "image/png")})
    assert r.status_code == 200 and any("transparent" in n for n in r.json()["notes"])


def test_deposer_une_arene_puis_la_salle_commune(client, content, assets):
    _, landscapes, _ = assets
    r = client.post("/admin/world-bosses/slime_titan/image", data={"slot": "arena"},
                    files={"image": ("arene.png", _png((1920, 1080), circle=False), "image/png")})
    assert r.status_code == 200 and r.json()["boss"]["arena_origin"] == "propre"
    notes = " ".join(r.json()["notes"])
    assert "portrait" in notes and "petite" in notes                        # paysage, et trop petite
    assert (landscapes / "arene_slime_titan.png").is_file()
    assert client.get("/admin/world-bosses/slime_titan/scene.jpg").status_code == 200

    r = client.post("/admin/world-bosses/arena-commune",
                    files={"image": ("salle.png", _png((2160, 2700), circle=False), "image/png")})
    assert r.status_code == 200 and r.json()["common"]["exists"]
    assert Image.open(landscapes / "arene_boss.png").size == (1080, 1350)    # réduite juste à la taille du cadre
    origins = {b["code"]: b["arena_origin"] for b in r.json()["bosses"]}
    assert origins.pop("slime_titan") == "propre" and set(origins.values()) == {"commune"}

    r = client.post("/admin/world-bosses/slime_titan/arena/delete")
    assert r.json()["boss"]["arena_origin"] == "commune" and not (landscapes / "arene_slime_titan.png").exists()
    r = client.post("/admin/world-bosses/arena-commune/delete")
    assert not r.json()["common"]["exists"] and {b["arena_origin"] for b in r.json()["bosses"]} == {"zone"}


def test_ce_qui_est_refuse(client, content, assets):
    bad = client.post("/admin/world-bosses/slime_titan/image", data={"slot": "boss"},
                      files={"image": ("notes.png", b"pas une image", "image/png")})
    assert bad.status_code == 400 and "illisible" in bad.json()["error"]
    assert client.post("/admin/world-bosses/slime_titan/image", data={"slot": "boss"}).status_code == 400
    assert client.post("/admin/world-bosses/inconnu/image", data={"slot": "boss"},
                       files={"image": ("a.png", _png(), "image/png")}).status_code == 404
    assert client.post("/admin/world-bosses/slime_titan/image", data={"slot": "autre"},
                       files={"image": ("a.png", _png(), "image/png")}).status_code == 400


def test_la_fiche_montre_les_images_et_l_enregistrement_les_garde(client, content):
    r = client.get("/admin/world-bosses/gobelin_warlord/edit")
    assert r.status_code == 200 and 'id="wb-data"' in r.text and "wb-delete" in r.text
    before = _bosses(content)["gobelin_warlord"]["image_name"]
    r = client.post("/admin/world-bosses/gobelin_warlord", data={"name": "Seigneur renommé"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/edit?saved=1")
    assert _bosses(content)["gobelin_warlord"]["image_name"] == before       # le formulaire n'efface pas l'image
