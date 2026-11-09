"""Admin web : cartes à collectionner (demande de l'auteur, 10/11/2026) —
réglages des boosters, fiches des cartes, chapitres, images et onglet
« Cartes » de la fiche joueur, sur une COPIE du contenu et des images."""

import io
import json
import shutil

import pytest
from PIL import Image

from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.session import get_db_session
from tests.webapp.test_admin_content_crud import _same_origin, content  # noqa: F401  (fixtures)
from tests.webapp.test_admin_pages_smoke import client  # noqa: F401  (fixture)


@pytest.fixture
def cards(content, monkeypatch, tmp_path):
    """cards.json et assets/cards copiés : le site écrit dans la copie."""
    art = tmp_path / "cards_art"
    shutil.copytree(card_loader.CARD_ART, art)
    monkeypatch.setattr(card_loader, "CONTENT_PATH", content / "cards.json")
    monkeypatch.setattr(card_loader, "CARD_ART", art)
    monkeypatch.setattr(card_loader, "DRAFT_ART", art / "ebauches")
    monkeypatch.setattr(card_loader, "BACK_FILE", art / "_dos.png")
    card_loader.clear_cache()
    yield content / "cards.json"
    card_loader.clear_cache()


def _saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _png(size=(300, 420), color=(200, 60, 120, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _params_form(params: cs.CardParams) -> dict:
    form = {"booster_price": str(params.booster_price), "brillante_pct": str(params.brillante_pct),
            "pity_boosters": str(params.pity_boosters), "brillante_petal_mult": str(params.brillante_petal_mult),
            "craft_mult": str(params.craft_mult)}
    if params.first_free:
        form["first_free"] = "1"
    for r in cs.RARITIES:
        form[f"normal_{r}"] = str(params.normal_rates.get(r, 0))
        form[f"hit_{r}"] = str(params.hit_rates.get(r, 0))
        form[f"petals_{r}"] = str(params.petals.get(r, 0))
    return form


def _card_form(**over) -> dict:
    form = {"name": "Spectre d'essai", "title": "Carte de test", "number": "62", "rarity": "rare",
            "category": "monstre", "chapter": "legendes", "element": "tenebre", "source": "slime",
            "effect_type": "monstre", "mob": "slime", "damage_pct": "4", "drop_pct": "8",
            "flavor": "Rien qu'un essai."}
    form.update(over)
    return form


def test_les_pages_s_affichent(client, cards):
    assert "Cartes à collectionner" in client.get("/admin/cards").text
    page = client.get("/admin/cards/settings")
    assert page.status_code == 200 and "Réglages des boosters" in page.text and "Les chapitres" in page.text
    assert "Titan Visqueux" in client.get("/admin/cards/slime_titan").text
    assert client.get("/admin/cards/new").status_code == 200
    assert client.get("/admin/cards/inconnue").status_code == 404
    face = client.get("/admin/cards/slime/face.png?w=180")
    assert face.status_code == 200 and Image.open(io.BytesIO(face.content)).width == 180
    assert client.get("/admin/cards/slime/face.png?brillante=1").headers["content-type"] == "image/png"
    assert client.get("/admin/cards/back.png").status_code == 200


def test_regler_les_boosters(client, cards):
    params = cs.CardParams(booster_price=3000, first_free=False, brillante_pct=5.5, pity_boosters=30,
                           craft_mult=12)
    r = client.post("/admin/cards/settings/params", data=_params_form(params), follow_redirects=False)
    assert r.status_code == 303
    assert _saved(cards)["params"]["booster_price"] == 3000
    assert card_loader.params() == params
    bad = _params_form(params)
    bad["normal_common"] = "10"                            # le total ne fait plus 100 %
    r = client.post("/admin/cards/settings/params", data=bad)
    assert r.status_code == 400 and "il faut 100 %" in r.text
    assert card_loader.params().normal_rates["common"] == params.normal_rates["common"]   # rien d'écrit


def test_la_simulation_suit_le_formulaire(client, cards):
    r = client.post("/admin/cards/settings/simulate", data=_params_form(cs.DEFAULT_PARAMS))
    assert r.status_code == 200 and "album complet" in r.text.lower()
    bad = _params_form(cs.DEFAULT_PARAMS)
    bad["hit_rare"] = "0"
    assert "il faut 100 %" in client.post("/admin/cards/settings/simulate", data=bad).text


def test_creer_deplacer_supprimer_une_carte(client, cards):
    r = client.post("/admin/cards/new", data=_card_form(number="3"), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/cards/spectre_d_essai?saved=created"
    saved = _saved(cards)["cards"]
    assert [c["number"] for c in sorted(saved, key=lambda c: c["number"])] == list(range(1, 63))
    assert next(c for c in saved if c["code"] == "spectre_d_essai")["number"] == 3
    assert card_loader.get_card("spectre_d_essai").effect == {"type": "monstre", "mob": "slime",
                                                              "damage_pct": 4, "drop_pct": 8}
    with get_db_session() as session:                      # les objets sont créés en base
        items = ItemRepository(session)
        assert items.get_by_code("carte_spectre_d_essai") is not None
        assert items.get_by_code("carte_spectre_d_essai_brillante") is not None
    assert client.post("/admin/cards/new", data=_card_form()).status_code == 400            # code déjà pris

    # Modifier : la carte part au bout, les autres reprennent leur place.
    r = client.post("/admin/cards/spectre_d_essai", data=_card_form(number="62", name="Spectre"),
                    follow_redirects=False)
    assert r.status_code == 303
    assert card_loader.get_card("spectre_d_essai").number == 62
    assert [c.number for c in card_loader.list_cards()] == list(range(1, 63))
    bad = client.post("/admin/cards/spectre_d_essai", data=_card_form(mob="licorne"))
    assert bad.status_code == 400 and "monstre inconnu" in bad.text

    r = client.post("/admin/cards/spectre_d_essai/delete", follow_redirects=False)
    assert r.status_code == 303
    assert card_loader.get_card("spectre_d_essai") is None
    assert [c.number for c in card_loader.list_cards()] == list(range(1, 62))


def test_une_carte_detenue_ne_se_supprime_pas(client, cards):
    from app.application.use_cases import cards as cards_uc

    with get_db_session() as session:
        cards_uc.admin_give_card(session, client.player_id, "slime")
    r = client.post("/admin/cards/slime/delete")
    assert r.status_code == 400 and "inventaires" in r.text
    assert card_loader.get_card("slime") is not None
    # Ni devenir une mythique (qui n'existe qu'en brillante).
    form = _card_form(name="Slime", number="1", rarity="mythic", chapter="clairiere", mob="slime")
    assert client.post("/admin/cards/slime", data=form).status_code == 400


def test_effets_boss_et_bonus(client, cards):
    form = _card_form(name="Boss d'essai", effect_type="boss", boss="slime_titan", boss_damage_pct="12",
                      guards=["slime", "gobelin"])
    assert client.post("/admin/cards/new", data=form, follow_redirects=False).status_code == 303
    assert card_loader.get_card("boss_d_essai").effect == {"type": "boss", "boss": "slime_titan",
                                                           "guards": ["slime", "gobelin"], "damage_pct": 12}
    bonus = _card_form(name="Bonus d'essai", category="divinite", effect_type="bonus",
                       bonus_key_0="xp_pct", bonus_value_0="3", bonus_key_1="gold_pct", bonus_value_1="2")
    assert client.post("/admin/cards/new", data=bonus, follow_redirects=False).status_code == 303
    assert card_loader.get_card("bonus_d_essai").effect == {"type": "bonus", "xp_pct": 3, "gold_pct": 2}


def test_apercu_avant_d_enregistrer(client, cards):
    r = client.post("/admin/cards/preview", data=_card_form(current_code="slime", name="Slime géant"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(r.content))
    assert image.width > image.height                     # normale | brillante


def test_images_de_la_carte_et_du_dos(client, cards):
    card = card_loader.get_card("borak")
    assert card_loader.art_origin(card) == "portrait"
    r = client.post("/admin/cards/borak/art/carte", files={"image": ("borak.png", _png(), "image/png")},
                    follow_redirects=False)
    assert r.status_code == 303 and card_loader.art_origin(card) == "carte"
    r = client.post("/admin/cards/borak/art/fullart", files={"image": ("plein.jpg", _png((900, 1260)), "image/jpeg")},
                    follow_redirects=False)
    assert r.status_code == 303
    full = card_loader.full_art_path(card)
    assert full is not None and max(Image.open(full).size) <= 1024
    bad = client.post("/admin/cards/borak/art/carte", files={"image": ("x.txt", b"pas une image", "text/plain")})
    assert bad.status_code == 400
    assert client.post("/admin/cards/borak/art/carte/delete", follow_redirects=False).status_code == 303
    assert card_loader.art_origin(card) == "portrait"
    r = client.post("/admin/cards/settings/back", files={"image": ("dos.png", _png((360, 504)), "image/png")},
                    follow_redirects=False)
    assert r.status_code == 303 and card_loader.BACK_FILE.is_file()


def test_les_chapitres(client, cards):
    r = client.post("/admin/cards/settings/chapters", data={"name": "Faille du Néant", "emoji": "🌌", "decor": ""},
                    follow_redirects=False)
    assert r.status_code == 303
    assert card_loader.get_chapter("faille_du_neant").name == "Faille du Néant"
    r = client.post("/admin/cards/settings/chapters/faille_du_neant",
                    data={"name": "Faille", "emoji": "🌌", "decor": "fracture_elementaire.png", "position": "1"},
                    follow_redirects=False)
    assert r.status_code == 303 and _saved(cards)["chapters"][0]["code"] == "faille_du_neant"
    assert client.post("/admin/cards/settings/chapters/clairiere/delete").status_code == 400       # des cartes
    assert client.post("/admin/cards/settings/chapters/faille_du_neant/delete", follow_redirects=False).status_code == 303
    assert all(c["code"] != "faille_du_neant" for c in _saved(cards)["chapters"])


def test_l_onglet_cartes_de_la_fiche_joueur(client, cards):
    from app.application.use_cases import cards as cards_uc

    pid = client.player_id
    assert client.post(f"/admin/players/{pid}/cartes/give", data={"card": "slime", "quantity": "2"},
                       follow_redirects=False).status_code == 303
    client.post(f"/admin/players/{pid}/cartes/give", data={"card": "grand_cerisier"})   # toujours brillante
    client.post(f"/admin/players/{pid}/cartes/state", data={"petals": "500", "since_top": "7"})
    with get_db_session() as session:
        coll = cards_uc.collection(session, pid)
    assert coll.normal == {"slime": 2} and coll.brillante == {"grand_cerisier": 1}
    assert (coll.petals, coll.since_top, coll.free_booster) == (500, 7, False)
    page = client.get(f"/admin/players/{pid}/cartes?edit=1")
    assert page.status_code == 200 and "Le Grand Cerisier" in page.text and "2/61" in page.text
    client.post(f"/admin/players/{pid}/cartes/remove", data={"card": "slime"})
    with get_db_session() as session:
        assert cards_uc.collection(session, pid).normal == {}
