"""Capacités spéciales de monstres en combat de groupe.

- gobelin_runique : explosion à la mort (3× attaque à chaque joueur, esquivable,
  les morts perdent leurs récompenses = survived False).
- gobelin_assassin : frappe d'ouverture prioritaire, toujours critique, cible la
  plus faible, série de kills (×2, ×3, …) tant qu'elle tue.
"""

from datetime import datetime, UTC

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.mob_ability_service import get_mob_abilities
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats

EXPLOSION = {"death_explosion": {"attack_multiplier": 3}}
ASSASSIN = {"opening_assassinate": {}}


def _mob(*, hp, attack, defense=0, speed=1, crit_chance=0, crit_damage=100, dodge=0):
    now = datetime.now(UTC)
    return MobDefinition(
        id=1, code="m", name="Mob", description="", image_name=None, family="gobelin",
        max_hp=hp, current_hp=hp, attack=attack, defense=defense, speed=speed,
        crit_chance=crit_chance, crit_damage=crit_damage, dodge=dodge, hp_regeneration=0,
        xp_reward=10, gold_reward=5, spawn_weight=1, loot_table=None,
        created_at=now, updated_at=now,
    )


def _player(pid, *, hp, attack=10, defense=0, speed=5, dodge=0, crit_chance=0):
    return {
        "player_id": pid, "user_id": 100 + pid, "name": f"P{pid}",
        "avatar_url": None, "current_hp": hp, "max_hp": hp,
        "stats": Stats(max_hp=hp, attack=attack, defense=defense, speed=speed,
                       crit_chance=crit_chance, crit_damage=150, dodge=dodge,
                       hp_regeneration=0),
    }


def _contrib(result, pid):
    return next(c for c in result.contributions if c.player_id == pid)


# ─────────────────────────────── explosion ───────────────────────────────

def test_death_explosion_hits_and_can_kill_survivors():
    svc = PartyCombatService()
    # Mob à 1 PV : tué au 1er coup. attack 50, def 0 → explosion 150 par joueur.
    mob = _mob(hp=1, attack=50, speed=1)
    party = [_player(1, hp=100, attack=30, speed=99)]  # 100 PV < 150 explosion
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=EXPLOSION)

    assert r.victory is True            # le mob est bien mort
    c = _contrib(r, 1)
    assert c.final_hp == 0              # tué par l'explosion
    assert c.survived is False          # → pas de récompenses (or/loot/kill)


def test_death_explosion_can_be_dodged():
    svc = PartyCombatService()
    mob = _mob(hp=1, attack=50, speed=1)
    party = [_player(1, hp=100, attack=30, speed=99, dodge=100)]  # esquive tout
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=EXPLOSION)

    assert r.victory is True
    c = _contrib(r, 1)
    assert c.final_hp == 100            # explosion esquivée → intact
    assert c.survived is True


def test_no_explosion_without_ability():
    svc = PartyCombatService()
    mob = _mob(hp=1, attack=50, speed=1)
    party = [_player(1, hp=100, attack=30, speed=99)]
    r = svc.fight_party_vs_mob(party=party, mob=mob)  # aucune capacité
    assert r.victory is True
    assert _contrib(r, 1).final_hp == 100  # aucun dégât post-mortem
    assert _contrib(r, 1).survived is True


def test_no_explosion_when_party_wiped_first():
    svc = PartyCombatService()
    # Gros mob rapide qui tue le joueur avant de mourir → pas d'explosion.
    mob = _mob(hp=100000, attack=999, speed=99)
    party = [_player(1, hp=50, attack=1, speed=1)]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=EXPLOSION)
    assert r.victory is False           # le mob survit → pas d'explosion


# ─────────────────────────────── assassinat ───────────────────────────────

def test_opening_strike_is_priority_and_always_crit():
    svc = PartyCombatService()
    # Mob crit_chance 0 mais force crit ×2 (crit_damage 200). attack 100 → 200.
    mob = _mob(hp=100000, attack=100, crit_damage=200, speed=1)
    # Joueur 150 PV : survivrait à un coup non-crit (100) mais pas au crit (200).
    party = [_player(1, hp=150, attack=1, speed=1)]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=ASSASSIN)

    assert _contrib(r, 1).final_hp == 0     # tué par l'ouverture → donc crit appliqué
    assert any("assassine" in (log.mob_action or "") for log in r.turn_logs)


def test_opening_kill_streak_escalates_then_stops():
    svc = PartyCombatService()
    # attack 100, crit ×2. Strikes : ×1=200, ×2=400, ×3=600 (dégâts).
    # Mob à 1 PV : le survivant (P3, rapide) le tue juste après l'ouverture,
    # ce qui isole la mécanique de série (pas de combat normal prolongé).
    mob = _mob(hp=1, attack=100, crit_damage=200, speed=1)
    party = [
        _player(1, hp=150, attack=1, speed=1),        # + faible → strike1 (200) tue
        _player(2, hp=350, attack=1, speed=1),        # strike2 (400) tue
        _player(3, hp=5000, attack=999, speed=99),    # strike3 (600) NE tue pas → stop
    ]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=ASSASSIN)

    assert _contrib(r, 1).survived is False   # exécuté (le + faible en 1er)
    assert _contrib(r, 2).survived is False   # exécuté en série (×2)
    # P3 a encaissé le 3e coup (600) mais survit (5000) → la série s'arrête.
    assert _contrib(r, 3).final_hp == 5000 - 600
    assert _contrib(r, 3).survived is True


def test_opening_targets_weakest_first():
    svc = PartyCombatService()
    mob = _mob(hp=1, attack=100, crit_damage=200, speed=1)
    # P2 est le plus faible (PV) → visé en premier et exécuté ; P1 (costaud,
    # rapide) encaisse le strike2 puis achève le mob → isole la mécanique.
    party = [_player(1, hp=5000, attack=999, speed=99), _player(2, hp=150, attack=1, speed=1)]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=ASSASSIN)
    assert _contrib(r, 2).survived is False
    assert _contrib(r, 1).final_hp == 5000 - 400   # seulement le strike2 (×2) encaissé


CHARM = {"charm": {}}


def test_charm_solo_is_instant_loss():
    svc = PartyCombatService()
    mob = _mob(hp=1000, attack=10, speed=1)
    party = [_player(1, hp=500, attack=50)]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=CHARM)
    assert r.victory is False                 # la succube gagne d'emblée
    assert _contrib(r, 1).final_hp == 0       # le joueur isolé est dévoré
    assert _contrib(r, 1).survived is False


def test_charm_mob_untouchable_while_charmed_alive():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=1, speed=1)
    # P1 = le plus puissant (gros PV) → charmé et intuable par le faible P2.
    party = [
        _player(1, hp=10000, attack=100, speed=5),  # charmé, écrase P2
        _player(2, hp=100, attack=1, speed=5),      # ne peut pas tuer P1
    ]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=CHARM)
    assert r.victory is False
    assert r.mob_remaining_hp == 100              # la succube n'a JAMAIS été touchée
    assert _contrib(r, 2).survived is False       # le charmé a tué son allié


def test_charm_freed_then_succube_killable():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=5, speed=1)
    # P1 le plus puissant (grosse attaque) MAIS fragile → charmé, mais P2 rapide
    # l'abat avant qu'il n'agisse, puis achève la succube.
    party = [
        _player(1, hp=50, attack=2000, speed=1),    # charmé (puissance max)
        _player(2, hp=500, attack=100, speed=99),   # libère P1 puis tue la succube
    ]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=CHARM)
    assert r.victory is True                        # succube tuée APRÈS le charmé
    assert _contrib(r, 1).survived is False         # le charmé (abattu) perd tout
    assert _contrib(r, 2).survived is True


def test_charm_targets_strongest_player():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=1, speed=1)
    party = [
        _player(1, hp=100, attack=10, speed=5),       # faible
        _player(2, hp=8000, attack=300, speed=5),     # le plus puissant → charmé
    ]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=CHARM)
    # P2 charmé → il écrase P1 (faible) et la succube reste intouchable.
    assert r.mob_remaining_hp == 100
    assert _contrib(r, 1).survived is False


def _first_player_hit_log(r):
    return next(log for log in r.turn_logs if log.player_actions)


def test_revive_needs_two_kills():
    svc = PartyCombatService()
    mob = _mob(hp=1, attack=1, speed=1)  # max_hp = 1
    party = [_player(1, hp=100000, attack=999, speed=99)]
    r = svc.fight_party_vs_mob(party=party, mob=mob,
                               mob_abilities={"revive": {"atk_pct": 100, "def_pct": 100}})
    assert r.victory is True
    assert any("renaît" in (log.mob_action or "") for log in r.turn_logs)


def test_shield_absorbs_before_hp():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=1, speed=1)  # bouclier = max_hp = 100
    party = [_player(1, hp=100000, attack=50, speed=99)]
    r = svc.fight_party_vs_mob(party=party, mob=mob,
                               mob_abilities={"shield": {"reset_on_kill": True}})
    first = _first_player_hit_log(r)
    assert first.mob_state["current_hp"] == 100      # PV intacts au 1er coup
    assert first.mob_state["shield"] == 50           # le bouclier a encaissé (100−50)
    assert r.victory is True                         # brisé puis tué


def test_fantome_dodges_first_attack_of_each_player():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=1, speed=1)
    party = [_player(1, hp=100000, attack=50, speed=99)]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities={"first_hit_dodge": {}})
    first = _first_player_hit_log(r)
    assert first.mob_state["current_hp"] == 100      # 1re attaque esquivée
    assert "dissipe" in (first.mob_action or "")


def test_multi_hit_strikes_three_times():
    svc = PartyCombatService()
    # 3 coups de 100 = 300 > 250 PV → le joueur meurt en un seul tour de mob.
    mob = _mob(hp=100000, attack=100, speed=99)
    party = [_player(1, hp=250, attack=1, speed=1)]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities={"multi_hit": {"hits": 3}})
    assert _contrib(r, 1).survived is False


def test_aoe_hits_every_player():
    svc = PartyCombatService()
    mob = _mob(hp=100000, attack=100, speed=100)
    party = [_player(i, hp=1000, attack=1, speed=1) for i in (1, 2, 3)]
    r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities={"aoe": {}}, max_turns=1)
    for pid in (1, 2, 3):
        assert _contrib(r, pid).final_hp == 900      # tous touchés (−100) en un tour


def test_lifesteal_heals_the_mob():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=50, speed=5)  # max_hp 100 ; guérit 20% des dégâts
    mob.max_hp = 1000
    party = [_player(1, hp=100000, attack=1, speed=1)]
    r = svc.fight_party_vs_mob(party=party, mob=mob,
                               mob_abilities={"lifesteal": {"pct": 20}}, max_turns=300)
    assert r.mob_remaining_hp > 100                  # a régénéré au-delà du départ


def test_chaman_heals_once_below_half():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=1, speed=5)  # max_hp 100
    party = [_player(1, hp=100000, attack=30, speed=5)]
    r = svc.fight_party_vs_mob(party=party, mob=mob,
                               mob_abilities={"heal_once_below": {"hp_pct": 50}})
    assert any("se soigne" in (log.mob_action or "") for log in r.turn_logs)
    assert r.victory is True                         # soigné une fois puis vaincu


def test_bleed_applies_damage_over_time():
    svc = PartyCombatService()
    mob = _mob(hp=100000, attack=50, speed=99)   # frappe souvent → pose des saignements
    party = [_player(1, hp=100000, attack=1, speed=1)]
    r = svc.fight_party_vs_mob(party=party, mob=mob,
                               mob_abilities={"bleed": {"pct": 10, "turns": 3, "max_stacks": 3}},
                               max_turns=40)
    assert any("Saignement" in (log.mob_action or "") for log in r.turn_logs)
    assert _contrib(r, 1).final_hp < 100000       # a perdu des PV (dont saignement)


def test_chain_replicate_cascades():
    svc = PartyCombatService()
    mob = _mob(hp=100000, attack=1, speed=100)
    party = [_player(1, hp=100000, attack=1, speed=1)]
    # chance 100% → réplique jusqu'au plafond (15) en une salve.
    r = svc.fight_party_vs_mob(party=party, mob=mob,
                               mob_abilities={"aoe": {}, "chain_replicate": {"chance": 100}},
                               max_turns=1)
    reps = sum("Réaction en chaîne" in (log.mob_action or "") for log in r.turn_logs)
    assert reps == 15


def test_absorb_removes_weaker_players_and_buffs():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=10, defense=5, speed=5)
    party = [
        _player(1, hp=2000, attack=200, speed=50),   # le plus fort → reste
        _player(2, hp=100, attack=10, speed=5),      # absorbé
    ]
    r = svc.fight_party_vs_mob(party=party, mob=mob,
                               mob_abilities={"absorb": {"chance": 100, "stat_pct": 50}})
    assert any("engloutit" in (log.mob_action or "") for log in r.turn_logs)
    assert _contrib(r, 2).damage_dealt == 0          # P2 englouti → n'a pas combattu
    assert _contrib(r, 1).damage_dealt > 0           # P1 seul au combat


def test_absorb_never_triggers_solo():
    svc = PartyCombatService()
    mob = _mob(hp=100, attack=5, speed=5)
    party = [_player(1, hp=5000, attack=100, speed=50)]
    r = svc.fight_party_vs_mob(party=party, mob=mob,
                               mob_abilities={"absorb": {"chance": 100, "stat_pct": 50}})
    assert not any("engloutit" in (log.mob_action or "") for log in r.turn_logs)
    assert r.victory is True                          # combat normal, seul


def test_all_ability_configs_run_without_error():
    from app.domain.services.mob_ability_service import MOB_ABILITIES
    svc = PartyCombatService()
    for code, cfg in MOB_ABILITIES.items():
        mob = _mob(hp=300, attack=20, defense=5, speed=8, crit_chance=10, crit_damage=150)
        party = [_player(1, hp=400, attack=40, speed=8),
                 _player(2, hp=500, attack=35, speed=6)]
        r = svc.fight_party_vs_mob(party=party, mob=mob, mob_abilities=cfg, max_turns=400)
        assert r is not None and isinstance(r.turns, int)


# ─────────────────────────────── registre ───────────────────────────────

def test_ability_registry_maps_codes():
    assert "death_explosion" in get_mob_abilities("gobelin_runique")
    assert "opening_assassinate" in get_mob_abilities("gobelin_assassin")
    assert "charm" in get_mob_abilities("succube")
    assert get_mob_abilities("gobelin") == {}
    assert get_mob_abilities(None) == {}
