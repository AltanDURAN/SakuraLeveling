"""Cartes à collectionner : règles pures (tirage, pitié, brillantes, pétales,
album, effets)."""

import random
from dataclasses import replace

from app.domain.services import card_service as cs
from app.domain.services.title_bonus_service import TitleBonuses

POOL = {"common": ["c1", "c2"], "uncommon": ["u1"], "rare": ["r1"], "epic": ["e1"],
        "legendary": ["l1", "l2"], "mythic": ["m1"]}


def _card(code, rarity="common", **kw) -> cs.CardDef:
    return cs.CardDef(code=code, number=kw.pop("number", 1), name=kw.pop("name", code.title()),
                      category=kw.pop("category", "monstre"), rarity=rarity, chapter="clairiere", **kw)


def test_les_taux_font_cent_pour_cent():
    assert abs(sum(cs.NORMAL_RATES.values()) - 100) < 1e-9
    assert abs(sum(cs.HIT_RATES.values()) - 100) < 1e-9
    assert "common" not in cs.HIT_RATES and "uncommon" not in cs.HIT_RATES


def test_un_booster_cinq_cartes_la_plus_rare_en_dernier_et_la_cinquieme_rare_ou_mieux():
    rng = random.Random(3)
    for _ in range(300):
        pulls, _ = cs.open_booster(POOL, rng, 0)
        assert len(pulls) == cs.BOOSTER_SIZE
        ranks = [cs.rarity_index(p.rarity) for p in pulls]
        assert ranks == sorted(ranks)
        assert ranks[-1] >= cs.rarity_index("rare")


def test_la_mythique_est_toujours_brillante():
    rng = random.Random(1)
    seen = 0
    for _ in range(20000):
        pulls, _ = cs.open_booster(POOL, rng, 0, brillante_pct=0)
        for p in pulls:
            if p.rarity == "mythic":
                seen += 1
                assert p.brillante
            else:
                assert not p.brillante
    assert seen > 0


def test_la_pitie_donne_un_legendaire_brillant_au_quarantieme_booster():
    rng = random.Random(5)
    since = 0
    for opened in range(1, 200):
        pulls, after = cs.open_booster(POOL, rng, since, brillante_pct=0)
        top = [p for p in pulls if p.rarity in cs.TOP_RARITIES]
        if since + 1 >= cs.PITY_BOOSTERS:
            assert top, "la pitié n'a pas joué"
        if any(p.pity for p in pulls):
            forced = next(p for p in pulls if p.pity)
            assert forced.rarity == "legendary" and forced.brillante
        assert after == (0 if top else since + 1)
        since = after


def test_compteur_de_pitie_et_rappel():
    assert cs.boosters_before_pity(0) == cs.PITY_BOOSTERS
    assert cs.boosters_before_pity(cs.PITY_BOOSTERS - 1) == 1


def test_brillantes_au_taux_demande():
    rng = random.Random(9)
    shiny = total = 0
    for _ in range(4000):
        pulls, _ = cs.open_booster(POOL, rng, 0)
        for p in pulls:
            if p.rarity != "mythic" and not p.pity:
                total += 1
                shiny += p.brillante
    assert abs(100 * shiny / total - cs.BRILLANTE_PCT) < 0.8


def test_une_rarete_vide_retombe_sur_la_plus_proche_en_dessous():
    rng = random.Random(2)
    pulls, _ = cs.open_booster({"common": ["c"], "rare": ["r"]}, rng, 0)
    assert {p.code for p in pulls} <= {"c", "r"}


def test_petales_et_fabrication():
    assert cs.petals_for("rare") == cs.PETALS["rare"]
    assert cs.petals_for("rare", brillante=True) == cs.PETALS["rare"] * cs.BRILLANTE_PETAL_MULT
    assert cs.craft_cost("epic") == cs.CRAFT_MULT * cs.PETALS["epic"]
    assert cs.duplicates(1) == 0 and cs.duplicates(4) == 3 and cs.duplicates(0) == 0
    assert cs.craftable(_card("x", "legendary"))
    assert not cs.craftable(_card("m", "mythic")), "la mythique n'existe qu'en brillante"


def test_album_normale_ou_brillante_compte():
    cards = [_card("a"), _card("b", "rare"), _card("c", "mythic")]
    album = cs.album(cards, {"a": 2}, {"b": 1, "c": 1})
    assert (album.owned, album.brillantes, album.total) == (3, 2, 3)
    assert album.complete and not album.brillante_complete
    assert album.by_rarity["common"] == (1, 1)
    half = cs.album(cards, {"a": 1}, {})
    assert half.percent == 33 and not half.complete
    assert cs.milestones_reached(33) == [25]
    assert cs.milestones_reached(100) == list(cs.ALBUM_MILESTONES)


def test_effets_agreges_une_fois_par_carte():
    monster = _card("gobelin", effect={"type": "monstre", "mob": "gobelin", "damage_pct": 3, "drop_pct": 5})
    boss = _card("titan", "legendary", category="boss",
                 effect={"type": "boss", "boss": "titan", "guards": ["slime"], "damage_pct": 10})
    kairos = _card("kairos", "epic", category="divinite", effect={"type": "bonus", "xp_pct": 2})
    cerisier = _card("cerisier", "mythic", category="mythique", effect={"type": "bonus", "gold_pct": 2, "xp_pct": 2})
    bonuses = cs.card_bonuses([monster, monster, boss, kairos, cerisier])
    assert bonuses.damage_vs_mob == {"gobelin": 3} and bonuses.drop_vs_mob == {"gobelin": 5}
    assert bonuses.boss_damage == {"titan": 10, "slime": 10}
    assert (bonuses.xp_pct, bonuses.gold_pct) == (4, 2)


def test_les_cartes_ne_jouent_que_dans_leur_combat():
    titles = TitleBonuses(damage_bonus_vs_family={"gobelin": 10}, drop_rate_bonus_vs_mob={"gobelin": 5})
    cards = cs.CardBonuses(damage_vs_mob={"gobelin": 3, "slime": 3}, drop_vs_mob={"gobelin": 5},
                           boss_damage={"titan": 10, "slime": 10})
    zone = cs.with_card_bonuses(titles, cards)
    assert zone.damage_bonus_vs_mob == {"gobelin": 3, "slime": 3}
    assert zone.drop_rate_bonus_vs_mob == {"gobelin": 10}
    assert abs(zone.damage_multiplier_vs("gobelin", "gobelin") - 1.13) < 1e-9
    raid = cs.with_card_bonuses(TitleBonuses(), cards, boss=True)
    # Au raid : la carte du boss (gardes compris), jamais celle du monstre « slime ».
    assert raid.damage_bonus_vs_mob == {"titan": 10, "slime": 10}
    assert raid.drop_rate_bonus_vs_mob == {}
    assert titles.damage_bonus_vs_mob == {} and titles.drop_rate_bonus_vs_mob == {"gobelin": 5}


def test_textes_des_effets():
    monster = _card("loup", name="Loup sacré", effect={"type": "monstre", "mob": "loup", "damage_pct": 3, "drop_pct": 5})
    assert cs.effect_text(monster) == "Contre Loup sacré : +3 % de dégâts, +5 % de butin"
    boss = _card("titan", "legendary", name="Titan", effect={"type": "boss", "boss": "titan", "damage_pct": 10})
    assert "Au raid contre Titan : +10 %" in cs.effect_text(boss)
    borak = _card("borak", "rare", effect={"type": "bonus", "fusion_discount_pct": 5})
    assert cs.effect_text(borak) == "−5 % d'or sur les fusions de Borak"


def test_arrondi_qui_garde_la_moyenne():
    rng = random.Random(4)
    values = [cs.stochastic_round(1.25, rng) for _ in range(20000)]
    assert set(values) == {1, 2}
    assert abs(sum(values) / len(values) - 1.25) < 0.02


def test_validation_d_une_serie():
    good = [_card("a", number=1, effect={"type": "monstre", "mob": "a"}),
            _card("b", number=2, effect={"type": "bonus", "xp_pct": 1})]
    assert cs.validate(good, mob_codes={"a"}) == []
    bad = [replace(good[0], rarity="ultra"), replace(good[1], number=4, effect={"type": "bonus", "nope": 1})]
    problems = cs.validate(bad, mob_codes={"a"})
    assert any("rareté" in p for p in problems) and any("numéros" in p for p in problems)
    assert any("bonus connu" in p for p in problems)


def test_le_bonus_contre_un_monstre_change_les_degats_du_moteur():
    from app.domain.services.party_combat_service import PartyCombatService
    from app.domain.value_objects.stats import Stats
    from tests.domain.test_party_combat_service import build_mob

    def fight(bonus):
        mob = build_mob(current_hp=10 ** 7, max_hp=10 ** 7, attack=1, defense=0, speed=5)
        stats = Stats(max_hp=1000, attack=100, defense=50, speed=5, crit_chance=0, crit_damage=150,
                      dodge=0, hp_regeneration=0)
        party = [{"player_id": 1, "user_id": 1, "name": "A", "avatar_url": "", "stats": stats,
                  "current_hp": stats.max_hp, "max_hp": stats.max_hp}]
        random.seed(12)
        titles = {1: TitleBonuses(damage_bonus_vs_mob={mob.code: bonus})} if bonus else {}
        result = PartyCombatService().fight_party_vs_mob(party, mob, title_bonuses_by_player=titles, max_turns=20)
        return result.contributions[0].damage_dealt

    assert fight(50) > fight(0) * 1.3
