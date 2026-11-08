"""Parcours d'arrivée (08/11/2026) : finir ou passer le tutoriel retient
l'aventure commencée, par compte Discord ; elle survit au reset du joueur,
comme le règlement accepté."""

from app.application.use_cases import member_access, rules, tutorial
from app.application.use_cases.reset_player import ResetPlayerUseCase
from tests.infrastructure.test_encounter_service import (  # noqa: F401  (fixtures)
    _create_player,
    session,
)


def test_passer_ou_finir_le_tutoriel_commence_l_aventure(session):
    alice = _create_player(session, discord_id=1, name="Alice")
    bob = _create_player(session, discord_id=2, name="Bob")
    assert member_access.access(session, 1) == member_access.MemberAccess(False, False)
    tutorial.skip(session, alice)
    tutorial.finish(session, bob)
    assert member_access.access(session, 1).adventurer and member_access.access(session, 2).adventurer
    assert not member_access.mark_adventurer(session, 1, "termine")        # la première date reste


def test_tous_les_comptes_et_leurs_etapes(session):
    alice = _create_player(session, discord_id=1, name="Alice")
    rules.accept(session, 1, 1)
    rules.accept(session, 3, 1)                                           # sans personnage
    tutorial.skip(session, alice)
    assert member_access.all_access(session) == {
        1: member_access.MemberAccess(True, True), 3: member_access.MemberAccess(True, False)}


def test_l_aventure_survit_au_reset_du_joueur(session):
    alice = _create_player(session, discord_id=1, name="Alice")
    rules.accept(session, 1, 1)
    tutorial.skip(session, alice)
    ResetPlayerUseCase().execute(session, alice)
    assert member_access.access(session, 1) == member_access.MemberAccess(True, True)
