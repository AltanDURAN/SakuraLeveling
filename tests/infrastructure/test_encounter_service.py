"""Tests d'EncounterService.apply_rewards — invariants V2 des récompenses
de combat de groupe.

EncounterService crée ses sessions DB via `get_db_session()` (pas
d'injection). On monkeypatch `get_db_session` au niveau du module pour
qu'il yield la session in-memory du test, ce qui nous permet d'inspecter
l'état post-rewards.
"""

from contextlib import contextmanager
from datetime import datetime, UTC

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.services import encounter_service as encounter_service_module
from app.application.services.encounter_service import EncounterService
from app.application.services.encounter_participant import EncounterParticipant
from app.bot.runtime.active_encounter import ActiveEncounter
from app.bot.runtime.encounter_mob_state import EncounterMobState
from app.domain.value_objects.party_battle_result import PartyBattleResult
from app.domain.value_objects.player_contribution import PlayerContribution
from app.domain.value_objects.stats import Stats
from app.infrastructure.db.base import Base

# Imports des modèles pour que create_all enregistre toutes les tables.
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel  # noqa: F401
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel  # noqa: F401
from app.infrastructure.db.models.role_trial_model import RoleTrialScoreModel  # noqa: F401
from app.infrastructure.db.models.world_boss_model import WorldBossModel, WorldBossParticipationModel  # noqa: F401
from app.infrastructure.db.models.player_title_model import PlayerTitleModel  # noqa: F401
from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel  # noqa: F401
from app.infrastructure.db.models.daily_quest_model import DailyQuestAssignmentModel  # noqa: F401
from app.infrastructure.db.models.player_mana_state_model import PlayerManaStateModel  # noqa: F401


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def session():
    """Session SQLite in-memory partagée pour tout le test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


@pytest.fixture()
def patch_get_db_session(monkeypatch, session):
    """Force EncounterService à utiliser la session de test.

    Le service appelle `get_db_session()` plusieurs fois ; on yield la
    MÊME session à chaque appel pour pouvoir l'inspecter en fin de test.
    On évite que `session.close()` soit appelé en sortie du context
    manager (la fixture `session` s'en charge à la fin).
    """

    @contextmanager
    def fake_get_db_session(atomic: bool = False):
        if atomic:
            from app.infrastructure.db.unit_of_work import atomic as _atomic

            with _atomic(session):
                yield session
        else:
            yield session

    monkeypatch.setattr(
        encounter_service_module,
        "get_db_session",
        fake_get_db_session,
    )


def _make_stats() -> Stats:
    return Stats(
        max_hp=100,
        attack=10,
        defense=5,
        crit_chance=0,
        crit_damage=100,
        dodge=0,
        hp_regeneration=0,
        speed=5,
    )


def _create_player(session, discord_id: int, name: str, level: int = 10) -> int:
    """Niveau 10 par défaut : au-dessus du coup de pouce des débuts (XP ×2)."""
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id,
        username=name.lower(),
        display_name=name,
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    session.add(player)
    session.flush()
    session.add(PlayerProgressionModel(
        player_id=player.id, level=level, xp=0, skill_points=0,
        created_at=now, updated_at=now,
    ))
    session.add(PlayerResourceModel(
        player_id=player.id, gold=0, daily_streak=0,
        created_at=now, updated_at=now,
    ))
    session.add(PlayerHealthStateModel(
        player_id=player.id, current_hp=100, updated_at=now,
    ))
    session.add(PlayerCareerStatsModel(
        player_id=player.id,
        created_at=now, updated_at=now,
    ))
    session.commit()
    return player.id


def _seed_mob(session, code: str = "test_mob", gold: int = 100, xp: int = 50) -> None:
    now = datetime.now(UTC)
    session.add(MobDefinitionModel(
        code=code,
        name="Test Mob",
        description="",
        image_name="",
        family="",  # famille vide : on évite le bonus de famille + les hooks
        max_hp=100, current_hp=100,
        attack=10, defense=5, speed=5,
        crit_chance=0, crit_damage=100, dodge=0,
        hp_regeneration=0,
        xp_reward=xp,
        gold_reward=gold,
        spawn_weight=1,
        loot_table_json=None,
        created_at=now, updated_at=now,
    ))
    session.commit()


def _build_encounter(participants: list[EncounterParticipant], mob_code: str = "test_mob") -> ActiveEncounter:
    enc = ActiveEncounter.create(
        mob_state=EncounterMobState(
            code=mob_code,
            name="Test Mob",
            image_name="",
            current_hp=0,
            max_hp=100,
            attack=10,
            defense=5,
            speed=5,
            crit_chance=0,
            crit_damage=100,
            dodge=0,
            hp_regeneration=0,
        ),
        victory_image_name="",
        defeat_image_name="",
        flee_image_name="",
    )
    for p in participants:
        enc.participants[p.user_id] = p
    return enc


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_apply_rewards_distributes_gold_to_survivors_only(session, patch_get_db_session):
    """Or aux survivants seulement (proportionnel à contribution), XP plein pour tous (mort inclus)."""
    p1_id = _create_player(session, discord_id=111, name="Alice")
    p2_id = _create_player(session, discord_id=222, name="Bob")
    _seed_mob(session, gold=100, xp=50)

    stats = _make_stats()
    survivor = EncounterParticipant(
        user_id=111, player_id=p1_id, display_name="Alice", avatar_url="",
        current_hp=80, max_hp=100, stats=stats,
    )
    dead = EncounterParticipant(
        user_id=222, player_id=p2_id, display_name="Bob", avatar_url="",
        current_hp=0, max_hp=100, stats=stats,
    )

    contributions = [
        PlayerContribution(
            player_id=p1_id, user_id=111, name="Alice",
            damage_dealt=100, damage_tanked=50, hp_healed=0,
            dodges=0, survived=True, final_hp=80, max_hp=100,
        ),
        PlayerContribution(
            player_id=p2_id, user_id=222, name="Bob",
            damage_dealt=20, damage_tanked=30, hp_healed=0,
            dodges=0, survived=False, final_hp=0, max_hp=100,
        ),
    ]

    result = PartyBattleResult(
        victory=True,
        turns=5,
        mob_name="Test Mob",
        mob_image_name="",
        mob_remaining_hp=0,
        surviving_players=["Alice"],
        defeated_players=["Bob"],
        xp_gained=50,
        gold_gained=100,
        summary="",
        turn_logs=[],
        contributions=contributions,
    )

    enc = _build_encounter([survivor, dead])

    summary = EncounterService().apply_rewards(enc, result)

    assert summary is not None
    assert summary.outcome == "victory"

    rewards_by_player = {r.player_id: r for r in summary.rewards}

    # Survivant : or > 0 (récupère TOUT le pool car le mort ne contribue pas
    # à la répartition gold — seuls les survivants y participent).
    assert rewards_by_player[p1_id].gold == 100
    assert rewards_by_player[p1_id].xp == 50

    # Mort : 0 or, mais XP plein (mort inclus dans l'XP V2).
    assert rewards_by_player[p2_id].gold == 0
    assert rewards_by_player[p2_id].xp == 50

    # Vérifie la persistance en DB
    p1_res = session.get(PlayerResourceModel, p1_id)
    p2_res = session.get(PlayerResourceModel, p2_id)
    assert p1_res.gold == 100
    assert p2_res.gold == 0

    # Progression : l'XP a été appliquée via ProgressionService.
    # 50 XP au niveau 10 : loin du palier, reste niveau 10 avec 50 XP.
    p1_prog = session.get(PlayerProgressionModel, p1_id)
    p2_prog = session.get(PlayerProgressionModel, p2_id)
    assert p1_prog.xp == 50
    assert p2_prog.xp == 50  # mort gagne aussi


def test_apply_rewards_increments_kills_only_for_survivors(session, patch_get_db_session):
    """+1 kill UNIQUEMENT pour les survivants, jamais pour les morts."""
    p1_id = _create_player(session, discord_id=111, name="Alice")
    p2_id = _create_player(session, discord_id=222, name="Bob")
    _seed_mob(session, gold=100, xp=50)

    stats = _make_stats()
    survivor = EncounterParticipant(
        user_id=111, player_id=p1_id, display_name="Alice", avatar_url="",
        current_hp=80, max_hp=100, stats=stats,
    )
    dead = EncounterParticipant(
        user_id=222, player_id=p2_id, display_name="Bob", avatar_url="",
        current_hp=0, max_hp=100, stats=stats,
    )

    contributions = [
        PlayerContribution(
            player_id=p1_id, user_id=111, name="Alice",
            damage_dealt=100, damage_tanked=50, hp_healed=0,
            survived=True, final_hp=80, max_hp=100,
        ),
        PlayerContribution(
            player_id=p2_id, user_id=222, name="Bob",
            damage_dealt=20, damage_tanked=30, hp_healed=0,
            survived=False, final_hp=0, max_hp=100,
        ),
    ]

    result = PartyBattleResult(
        victory=True,
        turns=5,
        mob_name="Test Mob",
        mob_image_name="",
        mob_remaining_hp=0,
        surviving_players=["Alice"],
        defeated_players=["Bob"],
        xp_gained=50,
        gold_gained=100,
        summary="",
        turn_logs=[],
        contributions=contributions,
    )

    enc = _build_encounter([survivor, dead])
    EncounterService().apply_rewards(enc, result)

    kill_rows = session.execute(select(PlayerMobKillModel)).scalars().all()
    kills_by_player = {row.player_id: row.kill_count for row in kill_rows}

    # Survivant : exactement +1 kill sur "test_mob".
    assert kills_by_player.get(p1_id) == 1
    # Mort : aucune ligne (pas de kill crédité).
    assert p2_id not in kills_by_player


def test_apply_rewards_defeat_grants_zero_rewards(session, patch_get_db_session):
    """En cas de défaite, AUCUN gold/xp/kill/loot n'est distribué."""
    p1_id = _create_player(session, discord_id=111, name="Alice")
    p2_id = _create_player(session, discord_id=222, name="Bob")
    _seed_mob(session, gold=100, xp=50)

    stats = _make_stats()
    a = EncounterParticipant(
        user_id=111, player_id=p1_id, display_name="Alice", avatar_url="",
        current_hp=0, max_hp=100, stats=stats,
    )
    b = EncounterParticipant(
        user_id=222, player_id=p2_id, display_name="Bob", avatar_url="",
        current_hp=0, max_hp=100, stats=stats,
    )

    contributions = [
        PlayerContribution(
            player_id=p1_id, user_id=111, name="Alice",
            damage_dealt=50, damage_tanked=80, hp_healed=0,
            survived=False, final_hp=0, max_hp=100,
        ),
        PlayerContribution(
            player_id=p2_id, user_id=222, name="Bob",
            damage_dealt=30, damage_tanked=60, hp_healed=0,
            survived=False, final_hp=0, max_hp=100,
        ),
    ]

    result = PartyBattleResult(
        victory=False,
        turns=4,
        mob_name="Test Mob",
        mob_image_name="",
        mob_remaining_hp=42,
        surviving_players=[],
        defeated_players=["Alice", "Bob"],
        xp_gained=0,
        gold_gained=0,
        summary="",
        turn_logs=[],
        contributions=contributions,
    )

    enc = _build_encounter([a, b])
    summary = EncounterService().apply_rewards(enc, result)

    assert summary is not None
    assert summary.outcome == "defeat"

    # Tous les rewards = 0
    for reward in summary.rewards:
        assert reward.gold == 0
        assert reward.xp == 0
        assert reward.items == []

    # DB : rien n'a bougé (or, XP, kills).
    for pid in (p1_id, p2_id):
        res = session.get(PlayerResourceModel, pid)
        prog = session.get(PlayerProgressionModel, pid)
        assert res.gold == 0
        assert prog.xp == 0

    kill_rows = session.execute(select(PlayerMobKillModel)).scalars().all()
    assert kill_rows == []


def test_persist_final_players_hp_sauve_aussi_le_mana(session, patch_get_db_session):
    """Le mana dépensé en combat de zone est conservé : il remonte ensuite
    hors combat (ManaRegenerationService), jamais pendant le combat."""
    from app.domain.value_objects.party_battle_turn_log import PartyBattleTurnLog
    from app.infrastructure.db.models.player_mana_state_model import PlayerManaStateModel

    pid = _create_player(session, 1, "Alice")
    state = {"player_id": pid, "current_hp": 42, "max_hp": 100, "current_mana": 13, "mana_max": 100}
    result = PartyBattleResult(
        victory=True, turns=1, mob_name="m", mob_image_name="", mob_remaining_hp=0,
        surviving_players=["Alice"], defeated_players=[], xp_gained=0, gold_gained=0, summary="",
        turn_logs=[PartyBattleTurnLog(turn_number=1, player_actions=[], mob_action="",
                                      players_state=[state], mob_state={})],
    )
    EncounterService().persist_final_players_hp(result)

    mana = session.execute(select(PlayerManaStateModel).where(PlayerManaStateModel.player_id == pid)).scalar_one()
    hp = session.execute(select(PlayerHealthStateModel).where(PlayerHealthStateModel.player_id == pid)).scalar_one()
    assert mana.current_mana == 13 and hp.current_hp == 42


def _won_by(player_id: int, discord_id: int, name: str = "Alice", survived: bool = True, final_hp: int = 80):
    return PartyBattleResult(
        victory=True, turns=5, mob_name="Test Mob", mob_image_name="", mob_remaining_hp=0,
        surviving_players=[name] if survived else [], defeated_players=[] if survived else [name],
        xp_gained=0, gold_gained=0, summary="", turn_logs=[],
        contributions=[PlayerContribution(player_id=player_id, user_id=discord_id, name=name,
                                          damage_dealt=100, survived=survived, final_hp=final_hp,
                                          max_hp=100)])


def _participant(player_id: int, discord_id: int, hp: int = 80, name: str = "Alice") -> EncounterParticipant:
    return EncounterParticipant(user_id=discord_id, player_id=player_id, display_name=name, avatar_url="",
                                current_hp=hp, max_hp=100, stats=_make_stats())


def test_l_xp_est_doublee_jusqu_au_niveau_10(session, patch_get_db_session):
    young = _create_player(session, discord_id=111, name="Alice", level=9)
    veteran = _create_player(session, discord_id=222, name="Bob", level=10)
    _seed_mob(session, xp=50)
    for pid, discord_id, expected, flag in ((young, 111, 100, True), (veteran, 222, 50, False)):
        enc = _build_encounter([_participant(pid, discord_id)])
        reward = EncounterService().apply_rewards(enc, _won_by(pid, discord_id)).rewards[0]
        assert reward.xp == expected and reward.newcomer_bonus is flag


def test_le_recapitulatif_connait_le_niveau_gagne_et_les_points(session, patch_get_db_session):
    pid = _create_player(session, discord_id=111, name="Alice", level=1)
    _seed_mob(session, xp=500)                  # ×2 : de quoi franchir plusieurs niveaux
    enc = _build_encounter([_participant(pid, 111)])
    reward = EncounterService().apply_rewards(enc, _won_by(pid, 111)).rewards[0]
    assert reward.level_before == 1 and reward.level_after > 2 and reward.levels_gained == reward.level_after - 1
    assert reward.stat_points == reward.levels_gained and reward.skill_points == reward.levels_gained


def test_un_mort_voit_aussi_son_niveau_gagne(session, patch_get_db_session):
    pid = _create_player(session, discord_id=111, name="Alice", level=1)
    _seed_mob(session, xp=500)
    enc = _build_encounter([_participant(pid, 111)])
    reward = EncounterService().apply_rewards(enc, _won_by(pid, 111, survived=False, final_hp=0)).rewards[0]
    assert reward.gold == 0 and reward.xp == 1000 and reward.levels_gained > 0


def test_un_titre_debloque_en_combat_est_remonte(session, patch_get_db_session, monkeypatch):
    from types import SimpleNamespace

    from app.application.services import title_unlock_service as module

    title = SimpleNamespace(code="bourreau", name="Bourreau", condition_value=1, condition_target="")
    monkeypatch.setattr(module, "list_for_condition",
                        lambda condition: [title] if condition == "kills_total" else [])
    pid = _create_player(session, discord_id=111, name="Alice")
    _seed_mob(session)
    enc = _build_encounter([_participant(pid, 111)])
    reward = EncounterService().apply_rewards(enc, _won_by(pid, 111)).rewards[0]
    assert reward.titles == ["Bourreau"]


def _mob_row(session):
    return session.execute(select(MobDefinitionModel)).scalars().first()


def test_les_pv_sont_relus_au_lancement_du_combat(session, patch_get_db_session):
    """Le bug signalé en mai : une potion bue entre le clic et le combat était
    perdue, les PV lus à l'inscription écrasaient tout."""
    pid = _create_player(session, discord_id=111, name="Alice")
    _seed_mob(session, code="slime_test")
    enc = _build_encounter([_participant(pid, 111, hp=20)], mob_code="slime_test")
    enc.participants[111].max_hp = 200          # inscription ancienne, pas à jour
    health = session.get(PlayerHealthStateModel, pid)
    health.current_hp = 90                      # la potion est bue après l'inscription
    health.updated_at = datetime.now(UTC)
    session.commit()

    result = EncounterService().resolve_active_encounter(enc)

    assert enc.participants[111].current_hp >= 90        # et plus les 20 PV de l'inscription
    assert result.turn_logs[0].players_state[0]["max_hp"] == enc.participants[111].max_hp


def test_un_joueur_tombe_ailleurs_ne_combat_pas(session, patch_get_db_session):
    alice = _create_player(session, discord_id=111, name="Alice")
    bob = _create_player(session, discord_id=222, name="Bob")
    _seed_mob(session, code="slime_test")
    enc = _build_encounter([_participant(alice, 111), _participant(bob, 222, name="Bob")], mob_code="slime_test")
    health = session.get(PlayerHealthStateModel, bob)
    health.current_hp = 0
    health.updated_at = datetime.now(UTC)
    session.commit()

    result = EncounterService().resolve_active_encounter(enc)

    assert list(enc.participants) == [111]
    assert {c.user_id for c in result.contributions} == {111}


def test_personne_ne_rejoint_un_combat_deja_joue(session, patch_get_db_session):
    pid = _create_player(session, discord_id=111, name="Alice")
    _seed_mob(session)
    enc = _build_encounter([])
    enc.resolved = True
    ok, message = EncounterService().register_participant(enc, 111, "Alice", "")
    assert not ok and "déjà commencé" in message
    enc.participants[111] = _participant(pid, 111)
    assert not EncounterService().unregister_participant(enc, 111)[0]
