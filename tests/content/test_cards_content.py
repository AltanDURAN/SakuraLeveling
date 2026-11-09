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
    problems = cs.validate(card_loader.list_cards(), {m["code"] for m in mobs}, {b["code"] for b in bosses})
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
    assert set(per_chapter) == {code for code, _ in cs.CHAPTERS}
    assert max(per_chapter.values()) <= 9


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


def test_les_monstres_dessines_ont_leur_image_de_carte():
    """Les monstres qui ont une image en jeu la prêtent à leur carte."""
    mobs = _json("mobs.json")
    mobs = mobs if isinstance(mobs, list) else mobs["mobs"]
    drawn = {m["code"] for m in mobs if m.get("image_name")}
    for card in card_loader.list_cards():
        if card.category == "monstre" and card.source in drawn:
            assert card_loader.art_path(card) is not None, card.code
