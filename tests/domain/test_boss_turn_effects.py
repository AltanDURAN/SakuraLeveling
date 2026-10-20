"""Soin et invocations du world boss : UNE fois par tour du boss.

La boucle de combat avance par ticks de jauge (on agit tous les 100/vitesse
ticks). Ces effets étaient appliqués à CHAQUE tick, soit 10 à 20 fois trop :
le Titan et le Dragon se soignaient plus vite que 4 joueurs de leur niveau ne
tapaient, et le raid était ingagnable.
"""

import random
from datetime import UTC, datetime

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats

START = 100_000
MAX = 1_000_000


def _boss(speed=10) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(
        id=1, code="boss", name="Boss", description="", image_name="", family="",
        max_hp=MAX, current_hp=START, attack=1, defense=0, speed=speed,
        crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
        xp_reward=0, gold_reward=0, spawn_weight=1, loot_table=[],
        created_at=now, updated_at=now, element="",
    )


def _party():
    stats = Stats(max_hp=10_000, attack=1, defense=1_000, speed=10, crit_chance=0,
                  crit_damage=100, dodge=0, hp_regeneration=0, mana_max=0, mana_regeneration=0)
    return [{"player_id": 1, "user_id": 1, "name": "p", "avatar_url": "", "stats": stats,
             "current_hp": stats.max_hp, "max_hp": stats.max_hp,
             "current_mana": 0, "mana_max": 0}]


def test_soin_une_fois_par_tour_du_boss():
    random.seed(0)
    # Immunité aux coups < 2 : le joueur (1 dégât) ne retire rien ; seul le
    # soin fait bouger les PV du boss.
    result = PartyCombatService().fight_party_vs_mob(
        _party(), _boss(speed=10), max_turns=20,
        damage_immunity_threshold=2, boss_heal_per_turn=10,
    )
    healed = result.mob_remaining_hp - START
    # 20 actions au total, joueur et boss à la même vitesse : ~10 tours du boss.
    assert 0 < healed <= 10 * 12, healed
