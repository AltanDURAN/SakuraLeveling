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


# ─────────────────────────────── registre ───────────────────────────────

def test_ability_registry_maps_codes():
    assert "death_explosion" in get_mob_abilities("gobelin_runique")
    assert "opening_assassinate" in get_mob_abilities("gobelin_assassin")
    assert get_mob_abilities("gobelin") == {}
    assert get_mob_abilities(None) == {}
