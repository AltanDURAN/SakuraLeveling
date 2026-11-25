"""Porte d'entrée avant le lancement d'une saison (25/11/2026, demande de
l'auteur) : pas d'avant-première. « testeurs » : un nouveau venu ne peut plus
accepter le règlement, les testeurs continuent ; « fermee » : tout le monde
attend l'ouverture, rôles retirés et jamais rendus ; le lancement rouvre."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.application.use_cases import entry_gate as gate_uc
from app.application.use_cases import rules as rules_uc
from app.application.use_cases.reset_season import reset_season
from app.bot import access, entry_gate, rules_gate
from app.infrastructure.config.settings import settings
from tests.bot.test_rules_gate import BUTTON, _interaction, store  # noqa: F401  (fixture)
from tests.infrastructure.test_encounter_service import session  # noqa: F401  (fixture)

ADMIN = 999
OPENS = datetime(2026, 12, 1, 19, tzinfo=UTC)


@pytest.fixture(autouse=True)
def gate(monkeypatch):
    monkeypatch.setattr(settings.__class__, "admin_ids", property(lambda self: [ADMIN]))
    entry_gate.forget()
    monkeypatch.setattr(entry_gate, "CACHE_SECONDS", 1e9)

    def put(mode):
        entry_gate._cache["gate"] = gate_uc.Gate(mode, OPENS)
        entry_gate._read_at["gate"] = __import__("time").monotonic()
    yield put
    entry_gate.forget()


def test_la_porte_est_ouverte_sans_reglage_et_le_lancement_la_rouvre(session):
    assert gate_uc.read(session) == gate_uc.Gate()
    gate_uc.write(session, gate_uc.CLOSED, OPENS)
    assert gate_uc.read(session) == gate_uc.Gate(gate_uc.CLOSED, OPENS)
    reset_season(session)
    assert gate_uc.read(session).is_open


def test_testeurs_un_nouveau_venu_ne_peut_plus_accepter_le_reglement(store, gate):
    gate(entry_gate.TESTERS)
    newcomer = _interaction(user_id=5, kind=BUTTON)
    asyncio.run(rules_gate.accept(newcomer))
    assert store == {} and "ouvriront" in newcomer.response.sent[0][0]
    assert "<t:" in newcomer.response.sent[0][0]                       # la date d'ouverture
    store[6] = 1                                                       # un testeur (déjà accepté)
    rules_gate._accepted.clear()
    assert asyncio.run(rules_gate.allow(_interaction(user_id=6)))      # il joue toujours


def test_fermee_personne_ne_joue_sauf_les_admins(store, gate):
    gate(entry_gate.CLOSED)
    store[6] = 1
    refused = _interaction(user_id=6)
    assert not asyncio.run(rules_gate.allow(refused))
    assert "ouvriront" in refused.response.sent[0][0]
    assert asyncio.run(rules_gate.allow(_interaction(user_id=6, name="reglement")))   # lire le règlement
    store[ADMIN] = 1
    assert asyncio.run(rules_gate.allow(_interaction(user_id=ADMIN)))
    button = _interaction(user_id=6, kind=BUTTON, ephemeral_message=True)
    asyncio.run(rules_gate.accept(button))
    assert "ouvriront" in button.response.edited[0]["content"]


def test_fermee_aucun_role_n_est_rendu(monkeypatch, gate):
    given = []

    async def give(member):
        given.append(member.id)
        return True

    monkeypatch.setattr(access, "ensure_start_rank_role", give)
    monkeypatch.setattr(access, "_state", lambda discord_id: access.member_access.MemberAccess(True, True))
    monkeypatch.setattr(access, "grant_adventurer", give)
    gate(entry_gate.CLOSED)
    asyncio.run(access.restore(SimpleNamespace(id=6, bot=False)))
    assert given == []
    monkeypatch.setattr(settings.__class__, "rank_roles", property(lambda self: {"F": 1}))
    assert asyncio.run(access.reconcile(SimpleNamespace(members=[SimpleNamespace(id=6, bot=False)]))) == (0, 0)
    gate(entry_gate.OPEN)
    asyncio.run(access.restore(SimpleNamespace(id=6, bot=False)))
    assert given == [6, 6]


def test_fermer_la_porte_retire_les_roles_sauf_aux_admins_et_aux_bots(monkeypatch):
    monkeypatch.setattr(access, "journey_role_ids", lambda: {1, 2})
    removed = []

    def member(member_id, *roles, bot=False):
        async def remove_roles(*held, reason=None):
            removed.append((member_id, sorted(r.id for r in held)))
        return SimpleNamespace(id=member_id, bot=bot, display_name=str(member_id),
                               roles=[SimpleNamespace(id=r) for r in roles], remove_roles=remove_roles)

    guild = SimpleNamespace(members=[member(6, 1, 2, 7), member(ADMIN, 1, 2), member(8, 1, bot=True), member(9, 7)])
    assert asyncio.run(entry_gate.lock_out(guild)) == (1, [])
    assert removed == [(6, [1, 2])]
