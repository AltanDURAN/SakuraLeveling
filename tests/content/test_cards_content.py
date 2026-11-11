"""Série 1 des cartes (`cards.json`) : complète, cohérente avec le jeu."""

import json
from collections import Counter
from dataclasses import fields
from pathlib import Path

from app.domain.services import card_service as cs
from app.domain.services.mob_ability_service import GROUP_ELITES
from app.infrastructure.cards import card_loader

CONTENT = Path(__file__).resolve().parents[2] / "app" / "infrastructure" / "content"


def _json(name):
    data = json.loads((CONTENT / name).read_text(encoding="utf-8"))
    return data


def test_soixante_et_une_cartes_et_la_pyramide_des_raretes():
    cards = card_loader.list_cards()
    assert len(cards) == 61
    assert Counter(c.rarity for c in cards) == {"common": 18, "uncommon": 12, "rare": 12, "epic": 13,
                                                "legendary": 5, "mythic": 1}
    assert [c.number for c in cards] == list(range(1, 62))


def test_la_serie_est_valide_et_ses_references_existent():
    mobs = _json("mobs.json")
    mobs = mobs if isinstance(mobs, list) else mobs["mobs"]
    bosses = _json("boss_definitions.json")
    bosses = bosses if isinstance(bosses, list) else bosses.get("bosses", list(bosses.values()))
    problems = cs.validate(card_loader.list_cards(), {m["code"] for m in mobs}, {b["code"] for b in bosses},
                           chapters={c.code for c in card_loader.get_series().chapters})
    assert problems == []


def test_chaque_monstre_des_zones_ouvertes_a_sa_carte_l_elite_est_epique():
    zones = _json("farm_zones.json")["zones"]
    mobs = _json("mobs.json")
    mobs = mobs if isinstance(mobs, list) else mobs["mobs"]
    open_families = {f for z in zones for f in z.get("families", [])}
    expected = {m["code"] for m in mobs if m.get("family") in open_families}
    monster_cards = {c.source: c for c in card_loader.list_cards() if c.category == "monstre"}
    assert set(monster_cards) == expected
    for code, card in monster_cards.items():
        assert (card.rarity == "epic") == (code in GROUP_ELITES), code


def test_une_page_d_album_par_chapitre_en_grille_trois_par_trois():
    per_chapter = Counter(c.chapter for c in card_loader.list_cards())
    assert set(per_chapter) == {c.code for c in card_loader.get_series().chapters}
    assert max(per_chapter.values()) <= 9


def test_les_reglages_et_les_chapitres_sont_dans_le_contenu():
    """Le site admin les modifie dans cards.json ; livrés aux valeurs de l'auteur."""
    data = _json("cards.json")
    assert cs.params_from_dict(data["params"]) == cs.DEFAULT_PARAMS
    assert cs.validate_params(card_loader.params()) == []
    assert [c["code"] for c in data["chapters"]] == [c.code for c in cs.DEFAULT_CHAPTERS]
    for chapter in card_loader.get_series().chapters:
        assert not chapter.decor or card_loader.decor_path(chapter.code) is not None, chapter.code


def test_chaque_effet_bonus_est_branche():
    hooked = {f.name for f in fields(cs.CardBonuses)}
    assert set(cs.BONUS_TEXTS) <= hooked
    for card in card_loader.list_cards():
        assert cs.effect_text(card), card.code


def test_objets_d_inventaire_une_normale_et_une_brillante_la_mythique_brillante_seulement():
    cards = card_loader.list_cards()
    codes = [card_loader.item_code(c.code, b) for c in cards for b in card_loader.variants(c)]
    assert len(codes) == len(set(codes)) == 2 * 61 - 1
    assert card_loader.parse_item_code(card_loader.item_code("slime", True)) == ("slime", True)
    assert card_loader.parse_item_code("potion_soin") is None
    mythic = next(c for c in cards if c.rarity == "mythic")
    assert card_loader.variants(mythic) == [True]


def test_chaque_carte_a_une_image():
    """L'image de l'auteur, du monstre, le portrait ou l'ébauche : jamais de « ? »."""
    for card in card_loader.list_cards():
        assert card_loader.art_path(card) is not None, card.code


def test_les_monstres_dessines_ont_leur_image_de_carte():
    """Les monstres qui ont une image en jeu la prêtent à leur carte."""
    mobs = _json("mobs.json")
    mobs = mobs if isinstance(mobs, list) else mobs["mobs"]
    drawn = {m["code"] for m in mobs if m.get("image_name")}
    for card in card_loader.list_cards():
        if card.category == "monstre" and card.source in drawn:
            assert card_loader.art_path(card) is not None, card.code


def test_un_boss_prete_son_image_propre_a_sa_carte(tmp_path, monkeypatch):
    """L'image déposée sur le site (boss_<code>.png) passe avant l'ébauche ;
    celle qu'il emprunte à un monstre en attendant, seulement en dernier
    recours (un boss renommé, sans ébauche, ne montre pas de « ? »)."""
    card = card_loader.get_card("slime_titan")
    assert card is not None and card.category == "boss"
    assets = tmp_path / "assets"
    (assets / "mobs").mkdir(parents=True)
    (assets / "cards" / "ebauches").mkdir(parents=True)
    monkeypatch.setattr(card_loader, "ASSETS", assets)
    monkeypatch.setattr(card_loader, "CARD_ART", assets / "cards")
    monkeypatch.setattr(card_loader, "DRAFT_ART", assets / "cards" / "ebauches")
    (assets / "mobs" / "slime.png").write_bytes(b"x")
    assert card_loader.art_origin(card) == "emprunt"
    (assets / "cards" / "ebauches" / "slime_titan.png").write_bytes(b"x")
    assert card_loader.art_origin(card) == "ebauche"
    (assets / "mobs" / "boss_slime_titan.png").write_bytes(b"x")
    assert card_loader.art_origin(card) == "boss"
