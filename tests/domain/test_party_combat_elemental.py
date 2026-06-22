"""Vérifie l'injection des multiplicateurs élémentaires dans le combat de groupe.

Les multiplicateurs sont optionnels : absents (encounters classiques) → aucun
effet ; présents (world boss) → modulent les dégâts ±50%.
"""

from datetime import datetime, UTC

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services.party_combat_service import PartyCombatService
from app.domain.value_objects.stats import Stats


def _mob(hp: int, attack: int, defense: int) -> MobDefinition:
    now = datetime.now(UTC)
    return MobDefinition(
        id=1, code="boss", name="Boss", description="", image_name="b.png",
        family="", max_hp=hp, current_hp=hp, attack=attack, defense=defense,
        speed=5, crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
        xp_reward=10, gold_reward=5, spawn_weight=1, loot_table=None,
        created_at=now, updated_at=now,
    )


def _party(attack: int = 100):
    return [{
        "player_id": 1, "user_id": 101, "name": "Hero",
        "avatar_url": "x", "current_hp": 100000, "max_hp": 100000,
        "stats": Stats(max_hp=100000, attack=attack, defense=10, speed=5,
                       crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0),
    }]


def test_outgoing_elemental_multiplier_increases_damage():
    svc = PartyCombatService()
    # Boss assez tanky pour ne pas mourir en 1 tour ; on compare le 1er coup.
    neutral = svc.fight_party_vs_mob(_party(), _mob(10_000_000, 1, 10))
    boosted = svc.fight_party_vs_mob(
        _party(), _mob(10_000_000, 1, 10),
        elemental_mult_by_player={1: 1.5},
    )
    dmg_neutral = neutral.turn_logs[0]  # 1er coup joueur
    dmg_boosted = boosted.turn_logs[0]
    # base = max(1, 100 - 10) = 90 ; boosté = round(90 * 1.5) = 135
    assert "90 dégâts" in dmg_neutral.player_actions[0]
    assert "135 dégâts" in dmg_boosted.player_actions[0]


def test_incoming_elemental_multiplier_increases_damage_taken():
    svc = PartyCombatService()
    # Boss assez tanky pour frapper plusieurs fois (joueur faible attaque),
    # joueur survit dans les deux cas. crit/dodge=0 → trajectoire déterministe.
    res_neutral = svc.fight_party_vs_mob(_party(attack=40), _mob(600, 100, 10))
    res_boosted = svc.fight_party_vs_mob(
        _party(attack=40), _mob(600, 100, 10),
        incoming_elemental_mult_by_player={1: 1.5},
    )
    # final_hp plus bas quand le joueur subit l'avantage élémentaire adverse.
    hp_neutral = res_neutral.contributions[0].final_hp
    hp_boosted = res_boosted.contributions[0].final_hp
    assert hp_boosted < hp_neutral


def test_no_multiplier_means_no_change():
    svc = PartyCombatService()
    res = svc.fight_party_vs_mob(_party(), _mob(10_000_000, 1, 10),
                                 elemental_mult_by_player={})
    assert "90 dégâts" in res.turn_logs[0].player_actions[0]
