"""Le contenu des fêtes de décembre (`seasonal_events.json`) respecte les
règles de l'auteur (10/11/2026) : un calendrier de l'Avent aux petites
récompenses (c'est le début de l'aventure), un cadeau de Noël plus gros selon
la gentillesse (50 / 100 / 150 %), les sucres d'orge les 7 jours avant Noël,
la boutique d'événement de Noël au 31, le Nouvel An sur 24 h."""

import json
from datetime import timedelta

from app.domain.services import seasonal_service as ss
from app.infrastructure.seasonal import seasonal_loader

ITEMS = {i["code"]: i for i in json.loads(
    (seasonal_loader.CONTENT_PATH.parent / "items.json").read_text(encoding="utf-8"))}
GEAR = {"arme", "bouclier", "tete", "corps", "accessoire"}


def _content():
    seasonal_loader.clear_cache()
    return seasonal_loader.raw(), seasonal_loader.get_content()


def test_le_contenu_est_valide():
    raw, content = _content()
    assert ss.validate(raw, set(ITEMS)) == []
    assert content.advent and content.christmas and content.new_year and content.drops and content.shops


def test_l_avent_reste_une_petite_recompense():
    _, content = _content()
    advent = content.advent
    assert advent.size == 24 and advent.start.month == 12 and advent.start.day == 1
    for n, day in enumerate(advent.days, start=1):
        for r in day:
            assert r.kind != ss.GOLD, f"case {n} : or fixe (il doit suivre le niveau)"
            if r.kind == ss.GOLD_PER_LEVEL:
                assert r.amount <= 30, f"case {n} : trop d'or"
            if r.kind == ss.ITEM:
                assert ITEMS[r.item]["category"] not in GEAR, f"case {n} : pas d'équipement"
    # Le principe (de petites récompenses), pas un compte exact : l'auteur règle
    # les cases depuis le site (12/11/2026 : 3 boosters le 24, soit 7 en tout)
    # et ce test ne doit pas rougir pour un booster. Au plus un tous les trois
    # jours en moyenne.
    boosters = sum(r.qty for day in advent.days for r in day if r.kind == ss.ITEM and r.item == "booster_offert")
    assert boosters <= advent.size // 3


def test_le_cadeau_de_noel_suit_la_regle_de_gentillesse():
    _, content = _content()
    c = content.christmas
    k = c.kindness
    assert (k.nice_from_pct, k.naughty_pct, k.nice_pct, k.angel_pct) == (50, 50, 100, 150)
    assert c.gift_day.month == 12 and c.gift_day.day == 25 and c.claim_until >= c.gift_day
    per_level = sum(r.amount for r in c.rewards if r.kind == ss.GOLD_PER_LEVEL)
    best_day = max(sum(r.amount for r in day if r.kind == ss.GOLD_PER_LEVEL) for day in content.advent.days)
    assert per_level >= 3 * best_day, "le cadeau doit être bien plus gros qu'une case"


def test_les_sucres_d_orge_puis_la_boutique_de_noel():
    _, content = _content()
    gift_day = content.christmas.gift_day
    drop = next(d for d in content.drops if d.item == "sucre_d_orge")
    assert drop.end == gift_day - timedelta(days=1) and (drop.end - drop.start).days + 1 == 7
    assert drop.per_kill == 1
    shop = next(s for s in content.shops if s.currency == "sucre_d_orge")
    assert shop.opens == gift_day and shop.closes.month == 12 and shop.closes.day == 31
    for code in ("fond_nuit_de_noel", "cadre_houx", "titre_givre"):
        offer = shop.offer(code)
        assert offer is not None and offer.limit == 1, code
        assert ITEMS[code]["category"] == "cosmetic"


def test_le_nouvel_an_dure_les_24_premieres_heures():
    _, content = _content()
    n = content.new_year
    assert n.day.month == 1 and n.day.day == 1 and n.hours == 24 and n.message
