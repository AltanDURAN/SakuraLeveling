"""Image de /affinites : rendu de tous les cas, et un talent caché ne fuit pas."""

from PIL import Image

from app.bot.rendering.affinities_image import build_affinity_cards, compose_affinities_image
from app.domain.services.element_talent_service import ElementTalent
from app.shared.enums import ALL_ELEMENTS


def _talents():
    t = {e.value: ElementTalent(5) for e in ALL_ELEMENTS}
    t["feu"] = ElementTalent(25, 1, 200)
    t["plante"] = ElementTalent(0)
    return t


def test_talent_cache_ne_fuit_pas():
    cards = build_affinity_cards({"feu": 150}, {}, _talents(), revealed=set())
    feu = next(c for c in cards if c.code == "feu")
    assert not feu.known and feu.talent == 0 and feu.cap == 100 and feu.boosts == 0
    assert feu.next_cost == 151  # le palier suit quand même le vrai plafond
    plante = next(c for c in cards if c.code == "plante")
    assert not plante.dead  # un élément mort non révélé reste un mystère


def test_talent_revele():
    cards = build_affinity_cards({"feu": 200}, {}, _talents(), revealed={"feu", "plante"})
    feu = next(c for c in cards if c.code == "feu")
    assert feu.known and feu.cap == 200 and feu.boosts == 1 and feu.next_cost is None
    assert next(c for c in cards if c.code == "plante").dead


def test_rendu_tous_les_cas(tmp_path):
    talents = _talents()
    for revealed, is_self, price in (
        (set(), True, 0),
        ({"feu", "plante"}, True, 4000),
        ({e.value for e in ALL_ELEMENTS}, True, None),
        ({"feu"}, False, 1500),
    ):
        cards = build_affinity_cards({"feu": 160, "eau": 12}, {"eau": 3}, talents, revealed)
        out = tmp_path / "aff.png"
        compose_affinities_image(str(out), display_name="Testeur", cards=cards,
                                 is_self=is_self, next_paper_price=price)
        with Image.open(out) as im:
            assert im.width == 1024 and im.height > 800
