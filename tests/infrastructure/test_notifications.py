"""Notifications « Confort » : qui les reçoit, et une seule fois par échéance."""

from datetime import datetime, timedelta, UTC

from app.bot.notifications import holders_of
from app.infrastructure.db.models.player_skill_allocation_model import (  # noqa: F401
    PlayerSkillAllocationModel,
)
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.skill_tree.skill_tree_loader import get_definition
from tests.infrastructure.test_reset_player_use_case import _create_player, session  # noqa: F401


def _feature_node(feature):
    from app.domain.services.skill_tree_service import SkillTreeService

    return SkillTreeService(get_definition()).nodes_granting_feature(feature)[0]


def test_seuls_les_detenteurs_de_la_case_au_maximum_sont_prevenus(session):
    alice = _create_player(session, 11, "Alice")
    bob = _create_player(session, 22, "Bob")
    node = _feature_node("notify_events")
    PlayerSkillAllocationRepository(session).upsert_level(alice, node.code, node.max_level)
    assert holders_of(session, "notify_events") == {alice: 11}
    assert bob not in holders_of(session, "notify_events")


def test_une_echeance_n_est_annoncee_qu_une_fois(session):
    pid = _create_player(session, 11, "Alice")
    repo = CooldownRepository(session)
    now = datetime.now(UTC)
    repo.upsert(player_id=pid, action_key="daily", last_used_at=now - timedelta(days=1),
                next_available_at=(now - timedelta(minutes=2)).replace(tzinfo=None))
    session.commit()
    due = repo.list_due_unnotified(now, now - timedelta(minutes=30), {"daily"})
    assert len(due) == 1
    repo.mark_notified(due[0][0], due[0][3])
    session.commit()
    assert repo.list_due_unnotified(now, now - timedelta(minutes=30), {"daily"}) == []


def test_une_vieille_echeance_n_est_pas_annoncee(session):
    pid = _create_player(session, 11, "Alice")
    repo = CooldownRepository(session)
    now = datetime.now(UTC)
    repo.upsert(player_id=pid, action_key="daily", last_used_at=now - timedelta(days=3),
                next_available_at=(now - timedelta(days=2)).replace(tzinfo=None))
    session.commit()
    assert repo.list_due_unnotified(now, now - timedelta(minutes=30), {"daily"}) == []
