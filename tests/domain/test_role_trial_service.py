"""Défis de rôle : règles pures (calendrier, variantes, semaine, podium) et
les deux mécaniques ajoutées au moteur (temps limité, escorte)."""

import random
from datetime import UTC, date, datetime

from app.domain.services import role_trial_service as rts
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats
from tests.domain.test_party_combat_service import build_mob


# ------------------------------------------------------------ calendrier --
def test_le_jour_et_la_semaine_suivent_l_heure_de_paris():
    # 23 h 30 UTC un samedi d'hiver = 0 h 30 dimanche à Paris.
    assert rts.trial_day(datetime(2026, 10, 31, 23, 30, tzinfo=UTC)) == date(2026, 11, 1)
    assert rts.week_start(date(2026, 11, 1)) == date(2026, 10, 26)   # lundi


def test_cloture_le_dimanche_a_20_h_heure_de_paris():
    # Dimanche 25/10/2026 (passage à l'heure d'hiver le jour même : UTC+1).
    assert not rts.is_closed(datetime(2026, 10, 25, 18, 59, tzinfo=UTC))   # 19 h 59
    assert rts.is_closed(datetime(2026, 10, 25, 19, 0, tzinfo=UTC))        # 20 h
    assert not rts.is_closed(datetime(2026, 10, 25, 23, 0, tzinfo=UTC))    # lundi 0 h


def test_variante_du_jour_la_meme_pour_tous_et_qui_change():
    days = [date(2026, 10, d) for d in range(1, 29)]
    for role in rts.ROLES:
        assert rts.variant_of_day(days[0], role) == rts.variant_of_day(days[0], role)
        assert len({rts.variant_of_day(d, role).code for d in days}) > 1


def test_graine_d_un_essai_stable_par_joueur_jour_role():
    d = date(2026, 10, 25)
    assert rts.attempt_seed(d, "dps", 7) == rts.attempt_seed(d, "dps", 7)
    assert rts.attempt_seed(d, "dps", 7) != rts.attempt_seed(d, "tank", 7)
    assert rts.attempt_seed(d, "dps", 7) != rts.attempt_seed(d, "dps", 8)


# --------------------------------------------------------------- semaine --
def test_semaine_les_cinq_meilleurs_jours():
    rows = [(1, "dps", date(2026, 10, 19 + i), score)
            for i, score in enumerate((10, 50, 20, 40, 30, 60, 5))]
    assert rts.weekly_scores(rows)["dps"] == {1: 60 + 50 + 40 + 30 + 20}


def test_general_moyenne_des_trois_roles_ramenes_a_cent():
    weekly = {"dps": {1: 1000, 2: 500}, "tank": {1: 100, 2: 400}, "soutien": {2: 300}}
    general = rts.general_scores(weekly)
    assert general[1] == round((100 + 25 + 0) / 3, 1)
    assert general[2] == round((50 + 100 + 100) / 3, 1)
    assert rts.ranking(general)[0][0] == 2


def test_classement_egalite_le_plus_ancien_devant_et_zero_exclu():
    assert rts.ranking({5: 10, 3: 10, 9: 0}) == [(3, 10), (5, 10)]


def test_or_du_podium_selon_le_niveau():
    assert [rts.reward_gold(i, 50) for i in range(4)] == [5000, 3000, 1500, 0]


# ----------------------------------------------------------------- moteur --
def _member(pid, hp=1000, atk=100, dfn=0, speed=10):
    st = Stats(max_hp=hp, attack=atk, defense=dfn, speed=speed, crit_chance=0, crit_damage=150,
               dodge=0, hp_regeneration=0, mana_max=0, mana_regeneration=0)
    return {"player_id": pid, "user_id": pid, "name": f"J{pid}", "avatar_url": "",
            "stats": st, "current_hp": hp, "max_hp": hp}


def test_limite_de_temps_la_vitesse_compte():
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=0, defense=0, speed=0)
    slow = PartyCombatService().fight_party_vs_mob([_member(1, speed=10)], mob, max_ticks=100)
    fast = PartyCombatService().fight_party_vs_mob([_member(1, speed=20)], mob, max_ticks=100)
    assert slow.turns == 10 and fast.turns == 20


def test_escorte_le_monstre_ne_vise_que_la_recrue_et_le_combat_s_arrete_a_sa_mort():
    random.seed(0)
    mob = build_mob(current_hp=10**9, max_hp=10**9, attack=500, defense=0, speed=10)
    party = [_member(1, hp=10_000, atk=1), _member(0, hp=1000, atk=1)]
    result = PartyCombatService().fight_party_vs_mob(party, mob, escort_ids={0})
    player, recruit = (next(c for c in result.contributions if c.player_id == p) for p in (1, 0))
    assert player.damage_tanked == 0 and player.survived
    assert not recruit.survived
    assert result.turns < 20


def test_un_essai_tank_ne_soigne_pas():
    from app.domain.services.combat_passives import CombatPassives

    healer = CombatPassives(healer=True, heal_power_multiplier=2)
    variant = rts.VARIANTS["tank"][0]
    st = _member(1, hp=5000, atk=200, dfn=50)["stats"]
    run = rts.run_trial("tank", variant, player_id=1, name="p", stats=st, passives=healer, seed=1)
    logs = " ".join(" ".join(t.player_actions) for t in run.result.turn_logs)
    assert "💚" not in logs and run.score > 0
