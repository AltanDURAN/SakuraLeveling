"""Pont admin web → bot : file de commandes + aiguillage.

On ne démarre PAS le vrai bot (il se connecterait à Discord et ferait spawner
de vrais monstres) : on branche des cogs factices et on vérifie que chaque
action est routée vers la bonne API, que le résultat est écrit, et qu'une
action inconnue est refusée.
"""

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.db.base import Base
from app.infrastructure.db.models.admin_command_model import AdminCommandModel  # noqa: F401
from app.infrastructure.db.repositories.admin_command_repository import (
    KNOWN_ACTIONS,
    AdminCommandRepository,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


# --------------------------- file de commandes ---------------------------

def test_enqueue_then_pending_then_mark(session):
    repo = AdminCommandRepository(session)
    cmd = repo.enqueue("spawn_event", {"event_type": "chest"}, requested_by=42)
    session.commit()

    pending = repo.list_pending()
    assert [c.id for c in pending] == [cmd.id]
    assert json.loads(pending[0].payload_json) == {"event_type": "chest"}

    repo.mark(cmd.id, "done", "Événement lancé.")
    session.commit()

    assert repo.list_pending() == []
    recent = repo.list_recent()
    assert recent[0].status == "done"
    assert recent[0].result == "Événement lancé."
    assert recent[0].executed_at is not None


def test_result_is_truncated(session):
    repo = AdminCommandRepository(session)
    cmd = repo.enqueue("stop_boss")
    session.commit()
    repo.mark(cmd.id, "failed", "x" * 900)
    session.commit()
    assert len(repo.list_recent()[0].result) == 500


# --------------------------- aiguillage ---------------------------

class _FakeEncounterCog:
    def __init__(self):
        self.calls = []

    def trigger_immediate_spawn(self, mob_code=None, element=None, channel_id=None):
        self.calls.append(("spawn", mob_code, element, channel_id))
        return True, f"spawn {mob_code or 'aléatoire'}"

    def force_end_encounter(self):
        self.calls.append(("stop",))
        return True, "combat arrêté"

    def request_early_resolve(self):
        self.calls.append(("resolve",))
        return True, "combat résolu"


class _FakeBossCog:
    def __init__(self):
        self.calls = []

    async def admin_spawn_boss(self, boss_code):
        self.calls.append(("spawn", boss_code))
        return True, f"boss {boss_code} spawné"

    async def admin_stop_boss(self):
        self.calls.append(("stop",))
        return True, "boss arrêté"


class _FakeEventCog:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    async def spawn_event(self, event_type):
        self.calls.append(event_type)
        return object() if self.ok else None


class _FakeBot:
    def __init__(self, cogs):
        self._cogs = cogs

    def get_cog(self, name):
        return self._cogs.get(name)


def _bridge(cogs):
    """Instancie le cog SANS démarrer sa boucle (qui exige un bot connecté)."""
    from app.bot.cogs.admin_bridge_cog import AdminBridgeCog

    bridge = AdminBridgeCog.__new__(AdminBridgeCog)
    bridge.bot = _FakeBot(cogs)
    return bridge


def _run(bridge, action, payload=None):
    return asyncio.run(bridge._execute(action, payload or {}))


def test_dispatch_spawn_encounter_specific_and_random():
    enc = _FakeEncounterCog()
    bridge = _bridge({"EncounterCog": enc})

    ok, msg = _run(bridge, "spawn_encounter", {"mob_code": "gobelin"})
    assert ok and "gobelin" in msg
    ok, _ = _run(bridge, "spawn_encounter", {})
    assert ok
    assert enc.calls == [("spawn", "gobelin", None, None), ("spawn", None, None, None)]


def test_dispatch_stop_and_resolve_encounter():
    enc = _FakeEncounterCog()
    bridge = _bridge({"EncounterCog": enc})
    assert _run(bridge, "stop_encounter")[0] is True
    assert _run(bridge, "resolve_encounter")[0] is True
    assert [c[0] for c in enc.calls] == ["stop", "resolve"]


def test_dispatch_boss_actions():
    boss = _FakeBossCog()
    bridge = _bridge({"WorldBossCog": boss})
    ok, msg = _run(bridge, "spawn_boss", {"boss_code": "slime_titan"})
    assert ok and "slime_titan" in msg
    assert _run(bridge, "stop_boss")[0] is True
    assert boss.calls == [("spawn", "slime_titan"), ("stop",)]


def test_dispatch_spawn_event_ok_and_failure():
    bridge_ok = _bridge({"EventCog": _FakeEventCog(ok=True)})
    ok, msg = _run(bridge_ok, "spawn_event", {"event_type": "chest"})
    assert ok and "chest" in msg

    bridge_ko = _bridge({"EventCog": _FakeEventCog(ok=False)})
    ok, msg = _run(bridge_ko, "spawn_event", {"event_type": "inconnu"})
    assert ok is False and "Impossible" in msg


def test_unknown_action_is_refused():
    ok, msg = _run(_bridge({}), "rm_-rf")
    assert ok is False and "inconnue" in msg.lower()


def test_missing_cog_is_reported_not_crashed():
    ok, msg = _run(_bridge({}), "spawn_encounter", {})
    assert ok is False and "EncounterCog" in msg


def test_every_known_action_is_dispatchable():
    """Aucune action déclarée ne doit tomber dans le trou du dispatcher."""
    cogs = {
        "EncounterCog": _FakeEncounterCog(),
        "WorldBossCog": _FakeBossCog(),
        "EventCog": _FakeEventCog(),
    }
    payloads = {"spawn_boss": {"boss_code": "x"}, "spawn_event": {"event_type": "chest"}}
    for action in KNOWN_ACTIONS:
        ok, msg = _run(_bridge(cogs), action, payloads.get(action))
        assert ok is True, f"{action} non dispatché : {msg}"
