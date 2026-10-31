"""Tutoriel /tuto (31/10/2026) : progression gardée, actions vérifiées,
3 potions du Grand Cerisier (100 % des PV) une seule fois."""

from datetime import UTC, datetime, timedelta

from app.application.use_cases import tutorial
from app.domain.services import tutorial_service as tsvc
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from tests.infrastructure.test_encounter_service import (  # noqa: F401  (fixtures)
    _create_player,
    session,
)


def _potions(session, pid) -> int:
    return next((e.quantity for e in InventoryRepository(session).list_by_player_id(pid)
                 if e.item_definition.code == tsvc.REWARD_ITEM), 0)


def _seed_reward(session):
    from app.infrastructure.db.models.item_model import ItemDefinitionModel

    session.add(ItemDefinitionModel(code=tsvc.REWARD_ITEM, name="Potion du Grand Cerisier", description="",
                                    category="consumable", rarity="rare", stackable=True,
                                    stat_bonuses_json='{"effect": "heal_percent", "value": 100}'))
    session.commit()


def test_la_progression_est_gardee_et_la_recompense_donnee_une_fois(session):
    _seed_reward(session)
    pid = _create_player(session, discord_id=1, name="Alice")
    assert tutorial.state(session, pid) == tutorial.TutorialState("en_cours", 0, False)
    tutorial.go_to(session, pid, 4)
    assert tutorial.state(session, pid).step == 4
    assert tutorial.finish(session, pid) == 3 and _potions(session, pid) == 3
    assert tutorial.finish(session, pid) == 0 and _potions(session, pid) == 3     # une seule fois
    assert tutorial.state(session, pid).status == "termine"


def test_passer_le_tutoriel_ne_donne_rien_mais_on_peut_y_revenir(session):
    _seed_reward(session)
    pid = _create_player(session, discord_id=1, name="Alice")
    tutorial.skip(session, pid)
    assert tutorial.state(session, pid).status == "passe" and _potions(session, pid) == 0
    tutorial.go_to(session, pid, 1)
    assert tutorial.state(session, pid).status == "en_cours"


def test_les_actions_sont_verifiees(session):
    pid = _create_player(session, discord_id=1, name="Alice")
    step = {s.check or s.code: s for s in tsvc.STEPS}
    assert not tutorial.check(session, pid, step["daily"])
    now = datetime.now(UTC)
    CooldownRepository(session).upsert(pid, "daily", now, now + timedelta(hours=20))
    assert tutorial.check(session, pid, step["daily"])
    assert not tutorial.check(session, pid, step["combat"])
    session.get(PlayerCareerStatsModel, pid).combats_fought = 1
    session.commit()
    assert tutorial.check(session, pid, step["combat"])
    assert not tutorial.check(session, pid, step["voyante"])
    assert tutorial.check(session, pid, step["arrivee"])                  # simple lecture
