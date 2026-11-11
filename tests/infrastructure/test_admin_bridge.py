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

    async def admin_spawn_boss(self, boss_code, element=None):
        self.calls.append(("spawn", boss_code) if element is None else ("spawn", boss_code, element))
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
    def __init__(self, cogs, guilds=()):
        self._cogs = cogs
        self.guilds = list(guilds)

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
    # L'élément choisi sur le site (sinon tiré au hasard par le bot).
    _run(bridge, "spawn_boss", {"boss_code": "slime_titan", "element": "feu"})
    assert boss.calls[-1] == ("spawn", "slime_titan", "feu")


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
        assert "non gérée" not in msg and "inconnue" not in msg.lower(), (
            f"{action} non dispatché : {msg}"
        )
        if action != "reset_journey_roles":  # dépend de RANK_ROLE_IDS, testé à part
            assert ok is True, f"{action} en échec : {msg}"


def test_reset_journey_roles_renvoie_tout_le_monde_au_reglement(monkeypatch):
    """Lancement de saison (décision de l'auteur, 09/11/2026) : chaque membre,
    admins compris, perd ses rangs et Aventurier ; ses autres rôles restent,
    les bots ne sont pas touchés, et le bot oublie les règlements acceptés
    qu'il gardait en mémoire."""
    from types import SimpleNamespace

    from app.bot import rules_gate
    from app.infrastructure.config.settings import Settings, settings

    monkeypatch.setattr(Settings, "rank_roles", property(lambda self: {"F": 1, "E": 2, "D": 3}))
    monkeypatch.setattr(settings, "adventurer_role_id", 9)
    monkeypatch.setattr(settings, "discord_guild_id", 500)
    monkeypatch.setitem(rules_gate._accepted, 10, 1)

    class Member:
        def __init__(self, member_id, role_ids, bot=False):
            self.id, self.bot, self.display_name = member_id, bot, f"m{member_id}"
            self.roles = [SimpleNamespace(id=r) for r in role_ids]

        async def remove_roles(self, *roles, reason=""):
            gone = {r.id for r in roles}
            self.roles = [r for r in self.roles if r.id not in gone]

    alice = Member(10, [1, 9, 77])          # Rang F, Aventurier, un rôle hors parcours
    bob = Member(11, [3, 2])                # deux rangs (reliquat manuel)
    newcomer = Member(12, [77])             # rien du parcours
    robot = Member(13, [1], bot=True)
    other_server = SimpleNamespace(id=600, members=[Member(14, [1, 9])])
    bridge = _bridge({})
    bridge.bot = _FakeBot({}, guilds=[SimpleNamespace(id=500, members=[alice, bob, newcomer, robot]), other_server])

    ok, msg = _run(bridge, "reset_journey_roles")

    assert ok and "2 membre(s)" in msg, msg
    assert [r.id for r in alice.roles] == [77] and bob.roles == [] and [r.id for r in newcomer.roles] == [77]
    assert [r.id for r in robot.roles] == [1], "un bot n'est pas touché"
    assert [r.id for r in other_server.members[0].roles] == [1, 9], "seul le serveur du jeu"
    assert rules_gate._accepted == {}
