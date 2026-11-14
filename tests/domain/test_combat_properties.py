"""Essais aléatoires du moteur de combat (revue du 14/11/2026).

Des centaines de combats tirés au hasard — compositions de 1 à 4 joueurs de
rôle, tous les niveaux, les 50 monstres avec leurs capacités — et des
propriétés qui doivent TOUJOURS tenir. 20 000 combats joués deux fois lors de
la revue : aucune violation. Ce test en garde 300 à chaque passage."""

import json
import random
from pathlib import Path

from app.domain.entities.mob_definition import MobDefinition
from app.domain.services import mob_ability_service
from app.domain.services.party_combat_service import PartyCombatService
from tests.content.test_rank_trial_balance import ROLES as reference_roles

FIELDS = set(MobDefinition.__dataclass_fields__)


def _mobs() -> list[MobDefinition]:
    raw = json.loads(Path("app/infrastructure/content/mobs.json").read_text(encoding="utf-8"))
    raw = raw["mobs"] if isinstance(raw, dict) else raw
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    base = {"id": 0, "created_at": now, "updated_at": now}
    return [MobDefinition(**{**base, **{k: v for k, v in m.items() if k in FIELDS}}) for m in raw]


def _fight(compo: str, level: int, mob: MobDefinition, seed: int):
    random.seed(seed)
    members, passives, tactics = reference_roles.party(compo, level)
    return PartyCombatService().fight_party_vs_mob(
        members, mob, mob_abilities=mob_ability_service.get_mob_abilities(mob.code),
        passives_by_player=passives, tactics_by_player=tactics)


def _digest(result) -> tuple:
    return (result.victory, result.turns, result.mob_remaining_hp,
            [(c.damage_dealt, c.damage_tanked, c.hp_healed, c.final_hp, c.final_mana) for c in result.contributions])


def test_des_centaines_de_combats_au_hasard_respectent_les_regles():
    mobs = _mobs()
    assert len(mobs) >= 50
    rng = random.Random(20261114)
    state = random.getstate()
    try:
        for _ in range(300):
            compo = "".join(rng.choice("DTSG") for _ in range(rng.randint(1, 4)))
            level = rng.choice([1, 5, 10, 20, 35, 50, 70, 100])
            mob = rng.choice(mobs)
            seed = rng.randrange(10 ** 9)
            where = f"{compo} niveau {level} contre {mob.code} (graine {seed})"
            result = _fight(compo, level, mob, seed)

            # Même graine, même combat : les défis et les calibrages en dépendent.
            assert _digest(_fight(compo, level, mob, seed)) == _digest(result), where
            assert result.mob_remaining_hp >= 0, where
            assert not (result.victory and result.mob_remaining_hp > 0), where
            for c in result.contributions:
                assert 0 <= c.final_hp <= max(c.max_hp, c.final_hp if not c.max_hp else c.max_hp), where
                assert c.survived == (c.final_hp > 0), where
                # Le mana ne remonte JAMAIS en combat : c'est une réserve qui se vide.
                assert 0 <= c.final_mana <= c.mana_max, where
                assert c.mana_spent >= 0 and c.damage_dealt >= 0 and c.damage_tanked >= 0 and c.hp_healed >= 0, where
    finally:
        random.setstate(state)
