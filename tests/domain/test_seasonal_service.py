"""Événements saisonniers — règles pures : récompenses à l'échelle, gentillesse
(ratio d'aide à la petite fille), cases de l'Avent, objets et boutiques
d'événement, fenêtre du Nouvel An, annonces une seule fois."""

from datetime import UTC, date, datetime

from app.domain.services import seasonal_service as ss

GOLD10 = {"kind": "gold_per_level", "amount": 10}
POTIONS = {"kind": "item", "item": "potion_soin", "qty": 3}

RAW = {
    "advent": {"enabled": True, "name": "Calendrier de l'Avent", "start": "2026-12-01",
               "days": [[GOLD10]] * 23 + [[POTIONS, {"kind": "gold", "amount": 500}]]},
    "christmas": {"enabled": True, "name": "Noël", "gift_day": "2026-12-25", "claim_until": "2026-12-31",
                  "rewards": [{"kind": "gold_per_level", "amount": 100}, {"kind": "item", "item": "booster_offert",
                                                                           "qty": 3}],
                  "kindness": {"nice_from_pct": 50, "naughty_pct": 50, "nice_pct": 100, "angel_pct": 150,
                               "unknown_pct": 100}},
    "drops": [{"code": "sucres", "name": "Sucres d'orge", "item": "sucre_d_orge", "per_kill": 1,
               "start": "2026-12-18", "end": "2026-12-24"}],
    "shops": [{"code": "lutins", "name": "L'atelier des lutins", "emoji": "🎁", "currency": "sucre_d_orge",
               "opens": "2026-12-25", "closes": "2026-12-31",
               "offers": [{"item": "cadre_houx", "price": 80, "limit": 1},
                          {"item": "potion_soin", "price": 4, "limit": 0}]}],
    "new_year": {"enabled": True, "day": "2027-01-01", "hours": 24, "title": "Bonne année !", "message": "…"},
}
CODES = {"potion_soin", "booster_offert", "sucre_d_orge", "cadre_houx"}


def _paris(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=ss.PARIS)


def test_les_recompenses_suivent_le_niveau_et_la_part_du_cadeau():
    gold = ss.parse_reward(GOLD10)
    assert gold.gold(1) == 10 and gold.gold(37) == 370
    potions = ss.parse_reward(POTIONS)
    # 3 × 50 % = 1,5 → 2 ; 3 × 150 % = 4,5 → 5 ; jamais moins de 1 ; 0 % retire la ligne.
    assert [ss.scale(potions, p).qty for p in (50, 100, 150)] == [2, 3, 5]
    assert ss.scale(ss.Reward(ss.ITEM, item="x", qty=1), 50).qty == 1
    assert ss.scale_all([potions, gold], 0) == ()
    assert ss.scale(gold, 150).amount == 15


def test_la_gentillesse_vient_du_ratio_d_aide_a_la_petite_fille():
    rules = ss.KindnessRules()
    assert ss.kindness(0, 0, rules).tier == ss.UNKNOWN and ss.kindness(0, 0, rules).pct == 100
    assert (ss.kindness(4, 0, rules).tier, ss.kindness(4, 0, rules).pct) == (ss.ANGEL, 150)
    assert (ss.kindness(2, 1, rules).tier, ss.kindness(2, 1, rules).pct) == (ss.NICE, 100)
    assert ss.kindness(1, 1, rules).tier == ss.NICE            # 50 % pile : sage
    assert (ss.kindness(1, 2, rules).tier, ss.kindness(1, 2, rules).pct) == (ss.NAUGHTY, 50)
    assert ss.kindness(0, 3, rules).pct == 50
    assert ss.kindness(1, 3, rules).ratio == 0.25


def test_une_case_par_jour_et_le_jour_meme():
    advent = ss.parse_content(RAW).advent
    assert advent.size == 24 and advent.end == date(2026, 12, 24)
    assert advent.day_of(date(2026, 11, 30)) is None and advent.day_of(date(2026, 12, 25)) is None
    assert advent.day_of(date(2026, 12, 1)) == 1 and advent.day_of(date(2026, 12, 24)) == 24
    states = ss.door_states(advent, date(2026, 12, 5), {1, 3})
    assert states[:6] == [ss.OPENED, ss.MISSED, ss.OPENED, ss.MISSED, ss.TODAY, ss.LOCKED]
    assert len(advent.rewards(24)) == 2 and advent.rewards(25) == ()


def test_le_cadeau_s_ouvre_du_25_au_31():
    c = ss.parse_content(RAW).christmas
    assert not c.gift_open(date(2026, 12, 24))
    assert c.gift_open(date(2026, 12, 25)) and c.gift_open(date(2026, 12, 31))
    assert not c.gift_open(date(2027, 1, 1))
    gift = c.gift_for(ss.kindness(3, 0, c.kindness))
    assert gift[0].amount == 150 and gift[1].qty == 5     # 150 % : 100 → 150 par niveau, 3 → 5 boosters


def test_objets_et_boutiques_d_evenement():
    content = ss.parse_content(RAW)
    drop = content.drops[0]
    assert [d.code for d in ss.active_drops(content.drops, date(2026, 12, 18))] == ["sucres"]
    assert not drop.active(date(2026, 12, 17)) and not drop.active(date(2026, 12, 25))
    shop = content.shop("lutins")
    assert not shop.is_open(date(2026, 12, 24)) and shop.is_open(date(2026, 12, 31))
    frame = shop.offer("cadre_houx")
    assert ss.max_buyable(frame, balance=500, bought=0) == 1        # limite 1
    assert ss.max_buyable(frame, balance=500, bought=1) == 0
    assert ss.max_buyable(frame, balance=79, bought=0) == 0         # pas assez de sucres d'orge
    assert ss.max_buyable(shop.offer("potion_soin"), balance=21, bought=40) == 5   # sans limite


def test_le_nouvel_an_dure_de_minuit_a_minuit_a_paris():
    n = ss.parse_content(RAW).new_year
    start, end = n.window()
    assert start == datetime(2026, 12, 31, 23, 0, tzinfo=UTC)       # minuit à Paris (UTC+1)
    assert end == datetime(2027, 1, 1, 23, 0, tzinfo=UTC)
    assert not n.active(_paris(2026, 12, 31, 23)) and n.active(_paris(2027, 1, 1, 0))
    assert n.active(_paris(2027, 1, 1, 23)) and not n.active(_paris(2027, 1, 2, 0))


def test_une_meme_benediction_ne_compte_pas_deux_fois():
    a, b, c, d = (datetime(2027, 1, 1, h, tzinfo=UTC) for h in (0, 6, 12, 18))
    assert ss.window_minus((a, d), None) == [(a, d)]
    assert ss.window_minus((a, d), (b, c)) == [(a, b), (c, d)]
    assert ss.window_minus((b, d), (a, c)) == [(c, d)]
    assert ss.window_minus((a, b), (c, d)) == [(a, b)]
    assert ss.window_minus((b, c), (a, d)) == []


def test_chaque_annonce_part_une_fois_et_encore_a_temps():
    content = ss.parse_content(RAW)
    keys = [a.key for a in ss.announcements(content)]
    # La boutique ouvre le jour de Noël : le matin de Noël la présente.
    assert keys == ["advent:2026-12-01", "drop:sucres:2026-12-18", "christmas:2026-12-25", "new_year:2027-01-01"]
    assert [a.key for a in ss.due(content, _paris(2026, 12, 1, 0), set())] == ["advent:2026-12-01"]
    assert ss.due(content, _paris(2026, 12, 3), {"advent:2026-12-01"}) == []
    late = ss.due(content, _paris(2026, 12, 10), set())            # bot éteint le 1er : rattrapée
    assert [a.key for a in late] == ["advent:2026-12-01"]
    assert ss.due(content, _paris(2026, 12, 26), set())[0].key == "christmas:2026-12-25"
    assert all(a.key != "advent:2026-12-01" for a in ss.due(content, _paris(2026, 12, 26), set()))
    assert [a.key for a in ss.due(content, _paris(2027, 1, 1, 0), set())] == ["new_year:2027-01-01"]


def test_ce_qui_se_passe_et_ce_qui_vient():
    content = ss.parse_content(RAW)
    before = ss.happening(content, _paris(2026, 11, 20))
    assert not before.anything and [label for _, label in before.upcoming][0].startswith("🎄")
    week = ss.happening(content, _paris(2026, 12, 20))
    assert week.advent_day == 20 and [d.code for d in week.drops] == ["sucres"] and not week.christmas_open
    xmas = ss.happening(content, _paris(2026, 12, 26))
    assert xmas.christmas_open and [s.code for s in xmas.shops] == ["lutins"] and xmas.advent_day is None
    assert week.signature() != xmas.signature()
    assert ss.happening(content, _paris(2027, 1, 1, 9)).new_year


def test_le_contenu_est_valide_ou_refuse_avec_ses_raisons():
    assert ss.validate(RAW, CODES) == []
    broken = {
        "advent": {**RAW["advent"], "days": [[], [{"kind": "item", "item": "inconnu", "qty": 1}]]},
        "christmas": {**RAW["christmas"], "claim_until": "2026-12-20"},
        "drops": [{**RAW["drops"][0], "end": "2026-12-01"}],
        "shops": [{**RAW["shops"][0], "offers": [{"item": "cadre_houx", "price": 0},
                                                  {"item": "cadre_houx", "price": 5}]}],
        "new_year": {**RAW["new_year"], "hours": 0},
    }
    problems = " | ".join(ss.validate(broken, CODES))
    for needle in ("case 1 : vide", "objet inconnu « inconnu »", "fin du cadeau est avant",
                   "la fin est avant le début", "vendu deux fois", "prix de « cadre_houx » ≥ 1",
                   "Nouvel An : la durée"):
        assert needle in problems, needle
    assert "date illisible" in " ".join(ss.validate({"advent": {"start": "1er décembre", "days": [[GOLD10]]}}))
