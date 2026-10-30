"""Récompenses d'une MEUTE en zone (`EncounterService.apply_rewards`) : XP et or
de la meute entière, une victoire par monstre."""

from sqlalchemy import select

from app.application.services.encounter_service import EncounterService
from app.application.services.encounter_participant import EncounterParticipant
from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.domain.services import pack_service
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.domain.value_objects.player_contribution import PlayerContribution
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel
from tests.infrastructure.test_encounter_service import (  # noqa: F401  (fixtures)
    _build_encounter,
    _create_player,
    _make_stats,
    _seed_mob,
    patch_get_db_session,
    session,
)


def test_une_meute_rapporte_la_somme_reduite_et_compte_chaque_victoire(session, patch_get_db_session):
    pid = _create_player(session, discord_id=111, name="Alice")
    _seed_mob(session, code="loup", gold=100, xp=50)
    _seed_mob(session, code="ours", gold=100, xp=50)
    enc = _build_encounter([EncounterParticipant(
        user_id=111, player_id=pid, display_name="Alice", avatar_url="",
        current_hp=80, max_hp=100, stats=_make_stats())], mob_code="loup")
    enc.pack = [EncounterMobState(code="ours", name="Ours", image_name="", current_hp=0, max_hp=87,
                                  attack=9, defense=5, speed=5, crit_chance=0, crit_damage=100,
                                  dodge=0, hp_regeneration=0)]
    result = PartyBattleResult(
        victory=True, turns=9, mob_name="Loup et Ours", mob_image_name="", mob_remaining_hp=0,
        surviving_players=["Alice"], defeated_players=[], xp_gained=0, gold_gained=0, summary="",
        turn_logs=[], contributions=[PlayerContribution(
            player_id=pid, user_id=111, name="Alice", damage_dealt=200, survived=True,
            final_hp=80, max_hp=100)])

    summary = EncounterService().apply_rewards(enc, result)

    reward = summary.rewards[0]
    assert reward.gold == pack_service.pack_reward([100, 100])
    assert reward.xp == pack_service.pack_reward([50, 50])
    kills = dict(session.execute(select(PlayerMobKillModel.mob_code, PlayerMobKillModel.kill_count)
                                 .where(PlayerMobKillModel.player_id == pid)).all())
    assert kills == {"loup": 1, "ours": 1}


def test_la_benediction_de_kairos_augmente_l_xp_des_combats(session, patch_get_db_session):
    from datetime import UTC, datetime, timedelta

    from app.infrastructure.db.models.offering_model import OfferingStateModel

    now = datetime.now(UTC).replace(tzinfo=None)
    session.add(OfferingStateModel(id=1, cycle=2, target=27_000, contributed=0, fills=1,
                                   deity_code="kairos", blessed_at=now,
                                   blessing_until=now + timedelta(hours=24)))
    pid = _create_player(session, discord_id=111, name="Alice")
    _seed_mob(session, code="loup", gold=100, xp=50)
    enc = _build_encounter([EncounterParticipant(
        user_id=111, player_id=pid, display_name="Alice", avatar_url="",
        current_hp=80, max_hp=100, stats=_make_stats())], mob_code="loup")
    result = PartyBattleResult(
        victory=True, turns=5, mob_name="Loup", mob_image_name="", mob_remaining_hp=0,
        surviving_players=["Alice"], defeated_players=[], xp_gained=0, gold_gained=0, summary="",
        turn_logs=[], contributions=[PlayerContribution(
            player_id=pid, user_id=111, name="Alice", damage_dealt=100, survived=True,
            final_hp=80, max_hp=100)])
    reward = EncounterService().apply_rewards(enc, result).rewards[0]
    assert reward.xp == 55 and reward.gold == 100      # +10 % d'XP, jamais d'or en plus


def test_la_pleine_lune_multiplie_xp_or_et_le_note_au_recap(session, patch_get_db_session):
    from datetime import UTC, datetime, timedelta

    from app.domain.services.lunar_service import DEFAULT_RULES, LunarEvent

    pid = _create_player(session, discord_id=111, name="Alice")
    _seed_mob(session, code="loup", gold=100, xp=50)
    enc = _build_encounter([EncounterParticipant(
        user_id=111, player_id=pid, display_name="Alice", avatar_url="",
        current_hp=80, max_hp=100, stats=_make_stats())], mob_code="loup")
    now = datetime.now(UTC)
    enc.lunar = LunarEvent("pleine_lune", now, now + timedelta(hours=8), rule=DEFAULT_RULES["pleine_lune"])
    result = PartyBattleResult(
        victory=True, turns=5, mob_name="Loup", mob_image_name="", mob_remaining_hp=0,
        surviving_players=["Alice"], defeated_players=[], xp_gained=0, gold_gained=0, summary="",
        turn_logs=[], contributions=[PlayerContribution(
            player_id=pid, user_id=111, name="Alice", damage_dealt=100, survived=True,
            final_hp=80, max_hp=100)])
    summary = EncounterService().apply_rewards(enc, result)
    assert (summary.rewards[0].xp, summary.rewards[0].gold) == (150, 300)
    assert summary.lunar_note.startswith("🌕 Pleine lune")
