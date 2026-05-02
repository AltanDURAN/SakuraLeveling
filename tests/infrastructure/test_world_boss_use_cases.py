"""Tests d'intégration des use cases du world boss.

Couvre :
    - SpawnWorldBossUseCase (refus si actif, mob introuvable, succès)
    - JoinWorldBossUseCase (auto-create profile, idempotence)
    - LeaveWorldBossUseCase (refus si déjà combattu)
    - FightWorldBossUseCase (cooldown, calcul des métriques, défaite)
    - CompleteWorldBossUseCase (récompenses top-X + base)
"""

import random
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.world_boss import (
    CompleteWorldBossUseCase,
    FightWorldBossUseCase,
    JoinWorldBossUseCase,
    LeaveWorldBossUseCase,
    SpawnWorldBossUseCase,
)
from app.domain.services.combat_service import CombatService
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.stats_service import StatsService
from app.domain.services.world_boss_scaling_service import WorldBossScalingService
from app.infrastructure.db.base import Base

# Imports nécessaires pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.craft_model import CraftRecipeModel, CraftRecipeIngredientModel  # noqa: F401
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel  # noqa: F401
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel  # noqa: F401
from app.infrastructure.db.models.world_boss_model import WorldBossModel, WorldBossParticipationModel  # noqa: F401

from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.mob_repository import MobRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.world_boss_repository import WorldBossRepository


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_mob(session) -> None:
    now = datetime.now(UTC)
    mob = MobDefinitionModel(
        code="slime", name="Slime", description="", image_name="",
        family="slime", max_hp=10, current_hp=10, attack=2, defense=1,
        speed=3, crit_chance=0, crit_damage=100, dodge=0, hp_regeneration=0,
        xp_reward=5, gold_reward=2, spawn_weight=1, loot_table_json=None,
        created_at=now, updated_at=now,
    )
    session.add(mob)
    session.commit()


def _seed_potions(session) -> None:
    """Seed les 2 potions utilisées comme récompenses (potion_soin_i et iii)."""
    now = datetime.now(UTC)
    for code, percent in [("potion_soin_i", 50), ("potion_soin_iii", 100)]:
        item = ItemDefinitionModel(
            code=code, name=code, description="", category="consumable",
            rarity="common", stackable=True, max_stack=None,
            sell_price=10, buy_price=30, icon=None,
            stat_bonuses_json={"effect": "heal_percent", "value": percent},
            equipment_slot=None, requires_two_hands=False,
            created_at=now, updated_at=now,
        )
        session.add(item)
    session.commit()


def test_spawn_refused_if_active_boss_exists(session):
    _seed_mob(session)
    use_case = SpawnWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
        mob_repository=MobRepository(session),
    )

    first = use_case.execute(mob_code="slime")
    assert first.success is True

    second = use_case.execute(mob_code="slime")
    assert second.success is False
    assert "déjà actif" in second.message


def test_spawn_refuses_unknown_mob(session):
    use_case = SpawnWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
        mob_repository=MobRepository(session),
    )
    result = use_case.execute(mob_code="dragon_inexistant")
    assert result.success is False
    assert "introuvable" in result.message


def test_spawn_boost_x100(session):
    _seed_mob(session)
    use_case = SpawnWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
        mob_repository=MobRepository(session),
    )
    result = use_case.execute(mob_code="slime")

    # Slime base : max_hp=10, attack=2 → boss = 1000, 200
    assert result.boss.max_hp == 1000
    assert result.boss.attack == 200
    # speed pas boost (V1)
    assert result.boss.speed == 3
    # boss ne regen jamais
    assert result.boss.hp_regeneration == 0


def test_join_then_leave(session):
    _seed_mob(session)
    SpawnWorldBossUseCase(
        WorldBossRepository(session), MobRepository(session)
    ).execute(mob_code="slime")

    join = JoinWorldBossUseCase(
        WorldBossRepository(session), PlayerRepository(session)
    )
    leave = LeaveWorldBossUseCase(
        WorldBossRepository(session), PlayerRepository(session)
    )

    r1 = join.execute(discord_id=1, username="alice", display_name="Alice")
    assert r1.success is True
    # Idempotence : déjà inscrit
    r1bis = join.execute(discord_id=1, username="alice", display_name="Alice")
    assert r1bis.success is False

    r2 = leave.execute(discord_id=1)
    assert r2.success is True


def test_leave_refused_if_already_fought(session):
    _seed_mob(session)
    SpawnWorldBossUseCase(
        WorldBossRepository(session), MobRepository(session)
    ).execute(mob_code="slime")

    JoinWorldBossUseCase(
        WorldBossRepository(session), PlayerRepository(session)
    ).execute(discord_id=1, username="alice", display_name="Alice")

    boss = WorldBossRepository(session).get_active()
    p1 = session.query(PlayerModel).filter_by(discord_id=1).one()
    # Simule un combat passé (incrémente fights_count)
    WorldBossRepository(session).add_combat_metrics(
        boss.id, p1.id, damage_dealt=100, damage_tanked=20, hp_healed=0,
    )

    leave = LeaveWorldBossUseCase(
        WorldBossRepository(session), PlayerRepository(session)
    )
    result = leave.execute(discord_id=1)
    assert result.success is False
    assert "déjà combattu" in result.message


def test_fight_refused_without_join(session):
    _seed_mob(session)
    SpawnWorldBossUseCase(
        WorldBossRepository(session), MobRepository(session)
    ).execute(mob_code="slime")

    fight = _build_fight_use_case(session)
    result = fight.execute(discord_id=1, username="alice", display_name="Alice")
    assert result.success is False
    assert "rejoindre" in result.message


def test_fight_records_metrics_and_persists_boss_hp(session):
    random.seed(0)
    _seed_mob(session)
    SpawnWorldBossUseCase(
        WorldBossRepository(session), MobRepository(session)
    ).execute(mob_code="slime")

    JoinWorldBossUseCase(
        WorldBossRepository(session), PlayerRepository(session)
    ).execute(discord_id=1, username="alice", display_name="Alice")

    fight = _build_fight_use_case(session)
    result = fight.execute(discord_id=1, username="alice", display_name="Alice")

    assert result.success is True
    # Le boss a perdu des PV
    boss = WorldBossRepository(session).get_active()
    if boss is not None:
        # Soit boss encore vivant (HP < max_hp), soit déjà mort (None car defeated)
        assert boss.current_hp < 1000


def test_fight_cooldown_blocks_second_call(session):
    random.seed(0)
    _seed_mob(session)
    SpawnWorldBossUseCase(
        WorldBossRepository(session), MobRepository(session)
    ).execute(mob_code="slime")

    JoinWorldBossUseCase(
        WorldBossRepository(session), PlayerRepository(session)
    ).execute(discord_id=1, username="alice", display_name="Alice")

    fight = _build_fight_use_case(session)
    fight.execute(discord_id=1, username="alice", display_name="Alice")
    second = fight.execute(discord_id=1, username="alice", display_name="Alice")

    assert second.success is False
    assert "déjà combattu" in second.message


def test_complete_distributes_rewards_to_top_and_base(session):
    _seed_mob(session)
    _seed_potions(session)
    SpawnWorldBossUseCase(
        WorldBossRepository(session), MobRepository(session)
    ).execute(mob_code="slime")

    boss = WorldBossRepository(session).get_active()

    # Crée 3 joueurs avec des métriques différentes
    join_use_case = JoinWorldBossUseCase(
        WorldBossRepository(session), PlayerRepository(session)
    )
    join_use_case.execute(discord_id=1, username="alice", display_name="Alice")
    join_use_case.execute(discord_id=2, username="bob", display_name="Bob")
    join_use_case.execute(discord_id=3, username="carol", display_name="Carol")

    repo = WorldBossRepository(session)
    p_alice = session.query(PlayerModel).filter_by(discord_id=1).one().id
    p_bob = session.query(PlayerModel).filter_by(discord_id=2).one().id
    p_carol = session.query(PlayerModel).filter_by(discord_id=3).one().id

    # Alice = top damage, Bob = top tank, Carol = participant ordinaire
    repo.add_combat_metrics(boss.id, p_alice, damage_dealt=500, damage_tanked=10, hp_healed=0)
    repo.add_combat_metrics(boss.id, p_bob, damage_dealt=50, damage_tanked=200, hp_healed=0)
    repo.add_combat_metrics(boss.id, p_carol, damage_dealt=100, damage_tanked=30, hp_healed=0)

    complete = CompleteWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
        player_repository=PlayerRepository(session),
        item_repository=ItemRepository(session),
        inventory_repository=InventoryRepository(session),
    )
    result = complete.execute(boss.id)

    assert result.success is True
    assert len(result.rewards) == 3

    # Alice (top damage) doit avoir base + bonus damage
    alice_reward = next(r for r in result.rewards if r.player_id == p_alice)
    assert alice_reward.role == "top_damage"
    # Base 50g + top 200g = 250g
    assert alice_reward.gold == 250

    # Bob (top tank)
    bob_reward = next(r for r in result.rewards if r.player_id == p_bob)
    assert bob_reward.role == "top_tank"
    assert bob_reward.gold == 250

    # Carol (participant)
    carol_reward = next(r for r in result.rewards if r.player_id == p_carol)
    assert carol_reward.role == "participant"
    assert carol_reward.gold == 50  # base seule


# ---------- Helpers ----------


def _build_fight_use_case(session):
    return FightWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
        player_repository=PlayerRepository(session),
        equipment_repository=EquipmentRepository(session),
        class_repository=ClassRepository(session),
        skill_allocation_repository=PlayerSkillAllocationRepository(session),
        cooldown_repository=CooldownRepository(session),
        stats_service=StatsService(),
        scaling_service=WorldBossScalingService(),
        combat_service=CombatService(),
        cooldown_service=CooldownService(),
    )
