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


# ------------------------------------------------------ réglages (site admin) --
def test_les_reglages_par_defaut_sont_valables_et_se_relisent():
    assert cs.validate_params(cs.DEFAULT_PARAMS) == []
    assert cs.params_from_dict(cs.params_to_dict(cs.DEFAULT_PARAMS)) == cs.DEFAULT_PARAMS
    # Un champ absent ou illisible garde sa valeur par défaut.
    partial = cs.params_from_dict({"booster_price": "abc", "pity_boosters": 25, "petals": {"rare": 30}})
    assert partial.booster_price == cs.BOOSTER_PRICE and partial.pity_boosters == 25
    assert partial.petals["rare"] == 30 and partial.petals["epic"] == cs.PETALS["epic"]
    assert cs.params_from_dict(None) == cs.DEFAULT_PARAMS


def test_un_reglage_invalide_est_refuse():
    bad = cs.CardParams(normal_rates={"common": 50}, brillante_pct=150, craft_mult=0)
    problems = cs.validate_params(bad)
    assert any("100 %" in p for p in problems)
    assert any("brillante" in p for p in problems)
    assert any("Fabriquer" in p for p in problems)


def test_les_taux_et_la_pitie_suivent_les_reglages():
    only_epic = cs.CardParams(normal_rates={"epic": 100}, hit_rates={"legendary": 100}, brillante_pct=0)
    pulls, since = cs.open_booster(POOL, random.Random(1), 0, params=only_epic)
    assert [p.rarity for p in pulls] == ["epic"] * 4 + ["legendary"] and since == 0
    no_pity = cs.CardParams(normal_rates={"common": 100}, hit_rates={"rare": 100}, pity_boosters=0)
    pulls, since = cs.open_booster(POOL, random.Random(2), 500, params=no_pity)
    assert not any(p.pity for p in pulls) and since == 501
    assert cs.boosters_before_pity(10, no_pity) is None
    assert cs.boosters_before_pity(10, cs.CardParams(pity_boosters=12)) == 2
    # Un taux à zéro ne sort jamais, même au bout du tirage.
    rng = random.Random(3)
    assert {cs._roll({"common": 0.0, "rare": 1.0, "mythic": 0.0}, rng) for _ in range(500)} == {"rare"}


def test_petales_fabrication_et_chances_selon_les_reglages():
    params = cs.CardParams(petals={**cs.PETALS, "rare": 40}, brillante_petal_mult=3, craft_mult=7)
    assert cs.petals_for("rare", True, params) == 120 and cs.craft_cost("rare", params) == 280
    assert round(1 / cs.per_booster("legendary")) == 16 and round(1 / cs.per_booster("epic")) == 4
    assert cs.per_booster("mythic", cs.CardParams(normal_rates={"common": 100}, hit_rates={"rare": 100})) == 0
    assert cs.lowest_hit() == "rare"
    # Recycler un booster de doublons rapporte ~150 pétales avec les réglages de l'auteur.
    assert 120 < cs.expected_petals() < 180


def test_la_simulation_signale_un_album_impossible():
    cards = [_card("a", number=1), _card("b", "rare", number=2), _card("m", "mythic", number=3)]
    never = cs.CardParams(normal_rates={"common": 100}, hit_rates={"rare": 100})
    sim = cs.simulate_album(cards, never, runs=5, rng=random.Random(1), max_boosters=50)
    assert sim.capped == 5 and sim.full == 50
    sim = cs.simulate_album(cards[:2], cs.DEFAULT_PARAMS, runs=5, rng=random.Random(1))
    assert sim.capped == 0 and sim.mythic is None and sim.full <= 5


def test_la_validation_connait_les_chapitres_et_les_effets():
    card = _card("a", number=1, effect={"type": "monstre", "mob": "a", "damage_pct": 3, "drop_pct": 5})
    assert cs.validate([card], {"a"}, chapters={"clairiere"}) == []
    assert any("chapitre inconnu" in p for p in cs.validate([card], {"a"}, chapters={"autre"}))
    bad = replace(card, code="Mauvais Code", effect={"type": "monstre", "mob": "a", "damage_pct": 2.5})
    problems = cs.validate([bad], {"a"}, chapters={"clairiere"})
    assert any("minuscules" in p for p in problems) and any("entier" in p for p in problems)
    boss = _card("t", "legendary", number=1, category="boss",
                 effect={"type": "boss", "boss": "titan", "guards": ["nope"], "damage_pct": 10})
    assert any("garde inconnu" in p for p in cs.validate([boss], {"a"}, {"titan"}, chapters={"clairiere"}))
