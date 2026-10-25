"""Le mana des compétences actives (25/10/2026, demande de l'auteur).

Soin, provocation, riposte, coup double, protection, sauvetage… puisent dans
la réserve AUTOMATIQUEMENT, seulement quand l'effet sert ; réserve vide ⇒
l'effet n'a pas lieu. Le mana ne remonte jamais pendant un combat."""

import random

from app.domain.services.combat_passives import MANA_COSTS, CombatPassives
from app.domain.services.party_combat_service import PartyCombatService
from tests.domain.test_gear_passives_combat import gear, logs, member, mob


def _fight(party, m, passives, seed=0, **kw):
    random.seed(seed)
    return PartyCombatService().fight_party_vs_mob(party, m, passives_by_player=passives, **kw)


def _contrib(result, pid=1):
    return next(c for c in result.contributions if c.player_id == pid)


def test_le_soigneur_paie_chaque_soin_et_attaque_quand_la_reserve_est_vide():
    healer = CombatPassives(healer=True, heal_power_multiplier=2.0)
    cost = MANA_COSTS["heal_spell"]

    def soigneur(mana):
        p = member(1, speed=100, mana_max=10 * cost)
        p["current_hp"], p["current_mana"] = 100, mana   # sous 50 % : il veut se soigner
        return p

    rich = _fight([soigneur(10 * cost)], mob(attack=1, speed=1), {1: healer}, max_turns=3)
    assert _contrib(rich).mana_uses == {"heal_spell": 3}
    assert _contrib(rich).final_mana == 7 * cost and _contrib(rich).mana_spent == 3 * cost

    broke = _fight([soigneur(cost - 1)], mob(attack=1, speed=1), {1: healer}, max_turns=3)
    assert "heal_spell" not in _contrib(broke).mana_uses
    assert _contrib(broke).damage_dealt > 0          # il frappe à la place
    assert _contrib(broke).final_mana == cost - 1     # rien n'a été prélevé
    assert logs(broke).count("à court de mana") == 1  # prévenu une seule fois


def test_le_mana_ne_remonte_jamais_en_combat():
    p = member(1, mana_max=1000, hp_regeneration=500)
    p["current_mana"] = 40
    result = _fight([p], mob(), {1: gear("double_strike")}, max_turns=200)
    assert _contrib(result).final_mana == 40 - _contrib(result).mana_spent
    assert _contrib(result).final_mana <= 40


def test_une_competence_s_arrete_quand_la_reserve_est_vide():
    cost = MANA_COSTS["counter_attack"]
    p = member(1, max_hp=10**6, mana_max=2 * cost)
    p["current_hp"] = 10**6
    result = _fight([p], mob(speed=40), {1: gear("counter_attack")}, max_turns=300)
    assert _contrib(result).mana_uses == {"counter_attack": 2}
    assert _contrib(result).mana_dry > 0 and _contrib(result).final_mana == 0


def test_pas_de_provocation_payee_sans_allie_a_proteger():
    vaillant = CombatPassives(taunt_chance_pct=100)
    solo = _fight([member(1)], mob(), {1: vaillant}, max_turns=20)
    assert "taunt" not in _contrib(solo).mana_uses
    duo = _fight([member(1, speed=20), member(2)], mob(), {1: vaillant}, max_turns=20)
    # Une provocation par attaque du monstre au plus (elle ne vaut que pour la suivante).
    assert 0 < _contrib(duo).mana_uses["taunt"] <= 10


def test_le_vampire_ne_paie_pas_a_pv_pleins():
    vampire = CombatPassives(lifesteal_pct=5)
    result = _fight([member(1, speed=100)], mob(attack=1, speed=1), {1: vampire}, max_turns=3)
    assert "lifesteal" not in _contrib(result).mana_uses


def test_sans_cout_pour_les_outils_de_mesure():
    p = member(1, max_hp=10**6)
    p["current_hp"], p["current_mana"] = 10**6, 0
    result = _fight([p], mob(speed=40), {1: gear("counter_attack")}, max_turns=200, mana_costs={})
    assert _contrib(result).mana_uses.get("counter_attack", 0) > 0 and _contrib(result).mana_dry == 0
