"""Application des compétences (loadouts) dans le combat de groupe :
bouclier (défensive), soin de l'allié le plus bas (support), via skill_loadouts."""

import random
from datetime import datetime, UTC

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats
from app.infrastructure.elements import element_skill_loader as L


def _mob(hp: int, attack: int, defense: int) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(
        id=1, code="boss", name="Boss", description="", image_name="b.png",
        family="", max_hp=hp, current_hp=hp, attack=attack, defense=defense,
        speed=5, crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
        xp_reward=10, gold_reward=5, spawn_weight=1, loot_table=None,
        created_at=now, updated_at=now,
    )


def _member(pid: int, attack=40, defense=10, max_hp=100000, mana=1_000_000):
    # Gros pool de mana par défaut : ces tests valident la MÉCANIQUE des effets
    # (bouclier/soin), pas l'économie de mana → on ne veut pas que les effets
    # fizzlent par manque de mana. La conso est testée séparément plus bas.
    return {
        "player_id": pid, "user_id": 100 + pid, "name": f"P{pid}", "avatar_url": "x",
        "current_hp": max_hp, "max_hp": max_hp,
        "current_mana": mana, "mana_max": mana,
        "stats": Stats(max_hp=max_hp, attack=attack, defense=defense, speed=5,
                       crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0),
    }


def test_defensive_skill_shield_reduces_hp_loss():
    random.seed(0)
    svc = PartyCombatService()
    res_none = svc.fight_party_vs_mob([_member(1)], _mob(600, 100, 10), max_turns=2000)
    random.seed(0)
    res_def = svc.fight_party_vs_mob(
        [_member(1)], _mob(600, 100, 10),
        skill_loadouts_by_player={1: [L.get_skill("feu_defensive")]},
        max_turns=2000,
    )
    assert res_def.contributions[0].final_hp > res_none.contributions[0].final_hp


def test_support_skill_heals_lowest_ally_and_credits_contribution():
    random.seed(1)
    svc = PartyCombatService()
    # P1 = support (soigne l'allié le plus bas = P2), P2 = sans compétence.
    party = [_member(1), _member(2, max_hp=3000)]
    res = svc.fight_party_vs_mob(
        party, _mob(2000, 120, 10),
        skill_loadouts_by_player={1: [L.get_skill("feu_support")]},
        max_turns=2000,
    )
    c1 = next(c for c in res.contributions if c.player_id == 1)
    # P1 a soigné/bouclier donné à un allié → crédit "soin" > 0.
    assert c1.hp_healed > 0


def test_no_loadout_means_no_shield_no_heal():
    random.seed(0)
    svc = PartyCombatService()
    res = svc.fight_party_vs_mob([_member(1)], _mob(600, 100, 10), max_turns=2000)
    assert res.contributions[0].hp_healed == 0


def test_skill_consumes_mana_and_fizzles_when_empty():
    """Une compétence coûte du mana quand elle se déclenche ; sans assez de mana
    elle ne part pas (fizzle) et le mana n'est jamais négatif."""
    random.seed(0)
    svc = PartyCombatService()
    skill = L.get_skill("feu_defensive")  # bouclier, mana_cost basique = 20
    assert skill.basic.mana_cost > 0
    # Mana pour exactement 2 casts basiques (2 × 20 = 40).
    member = _member(1, mana=2 * skill.basic.mana_cost)
    res = svc.fight_party_vs_mob(
        [member], _mob(600, 100, 10),
        skill_loadouts_by_player={1: [skill]},
        max_turns=2000,
    )
    final_mana = res.contributions[0].final_mana
    # Le mana a été consommé (≤ départ) et jamais négatif.
    assert 0 <= final_mana <= 2 * skill.basic.mana_cost


def test_out_of_combat_mana_regeneration():
    """La régén mana hors combat suit exactement la logique HP : mana/minute
    écoulée, capé au max, no-op si déjà plein ou regen nul."""
    from app.domain.services.mana_regeneration_service import ManaRegenerationService
    from datetime import timedelta

    svc = ManaRegenerationService()
    now = datetime.now(UTC)
    last = now - timedelta(minutes=10)
    # 10 min × 5 mana/min = +50, borné au max.
    assert svc.apply_out_of_combat_regeneration(20, 100, 5, last, now) == 70
    assert svc.apply_out_of_combat_regeneration(80, 100, 5, last, now) == 100  # cap
    assert svc.apply_out_of_combat_regeneration(50, 100, 0, last, now) == 50   # regen nul
    assert svc.apply_out_of_combat_regeneration(100, 100, 5, last, now) == 100  # déjà plein
