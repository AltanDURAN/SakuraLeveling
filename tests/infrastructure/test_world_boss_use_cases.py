"""Tests d'intégration des use cases du world boss.

Couvre :
    - SpawnWorldBossUseCase (refus si actif, mob introuvable, succès)
    - JoinWorldBossUseCase (auto-create profile, idempotence)
    - LeaveWorldBossUseCase (refus si déjà combattu)
    - CompleteWorldBossUseCase (récompenses top-X + base)
"""

import random
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.world_boss import (
    CompleteWorldBossUseCase,
    JoinWorldBossUseCase,
    LeaveWorldBossUseCase,
    SpawnRandomWorldBossUseCase,
    SpawnWorldBossUseCase,
)
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
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
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
    """No-op laissé pour compatibilité — les tests refactored n'ont plus besoin
    de seed un mob (les BossDefinitions vivent dans le JSON content)."""
    pass


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
    )

    first = use_case.execute(boss_code="slime_titan")
    assert first.success is True

    second = use_case.execute(boss_code="slime_titan")
    assert second.success is False
    assert "déjà actif" in second.message


def test_spawn_refuses_unknown_mob(session):
    use_case = SpawnWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
    )
    result = use_case.execute(boss_code="dragon_inexistant")
    assert result.success is False
    assert "introuvable" in result.message


def test_spawn_uses_definition_stats(session):
    """Le spawn utilise les stats raw de la BossDefinition (JSON)."""
    use_case = SpawnWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
    )
    result = use_case.execute(boss_code="slime_titan")

    # slime_titan dans boss_definitions.json : max_hp=50000, attack=50, speed=8
    assert result.boss.max_hp == 50000
    assert result.boss.attack == 50
    assert result.boss.speed == 8
    # boss ne regen jamais
    assert result.boss.hp_regeneration == 0


def test_join_then_leave(session):
    _seed_mob(session)
    SpawnWorldBossUseCase(
        WorldBossRepository(session),
    ).execute(boss_code="slime_titan")

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
        WorldBossRepository(session),
    ).execute(boss_code="slime_titan")

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


# NOTE : les tests du combat SOLO (FightWorldBossUseCase) ont été retirés —
# le flux solo a été remplacé par le combat collectif
# (LaunchPartyFightWorldBossUseCase). Couverture combat collectif à ajouter.


def test_auto_spawn_refused_when_boss_active(session):
    SpawnWorldBossUseCase(
        WorldBossRepository(session),
    ).execute(boss_code="slime_titan")

    auto = SpawnRandomWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
    )
    decision = auto.execute(force=True)
    assert decision.spawned is False
    assert decision.reason == "boss_actif"


def test_auto_spawn_refused_during_respawn_cooldown(session):
    """Si un boss vient d'être tué, refuse le respawn pendant 7j."""
    from datetime import timedelta

    repo = WorldBossRepository(session)
    SpawnWorldBossUseCase(repo).execute(boss_code="slime_titan")
    boss = repo.get_active()
    repo.mark_defeated(boss.id)

    auto = SpawnRandomWorldBossUseCase(world_boss_repository=repo)

    # Maintenant : moins de 7j → refusé même en force
    decision = auto.execute(now=datetime.now(UTC), force=True)
    assert decision.spawned is False
    assert "cooldown" in decision.reason

    # 8j après : autorisé
    future = datetime.now(UTC) + timedelta(days=8)
    decision = auto.execute(now=future, force=True)
    assert decision.spawned is True


def test_auto_spawn_force_creates_random_boss(session):
    auto = SpawnRandomWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
    )
    decision = auto.execute(force=True, rng=random.Random(0))
    assert decision.spawned is True
    assert decision.boss is not None


def test_complete_triggers_level_up_when_xp_threshold_crossed(session):
    """Bug fix : l'XP des récompenses boss doit déclencher le level up via
    ProgressionService, pas juste incrémenter le compteur xp."""
    _seed_potions(session)
    SpawnWorldBossUseCase(WorldBossRepository(session)).execute(
        boss_code="slime_titan"
    )
    boss = WorldBossRepository(session).get_active()

    JoinWorldBossUseCase(
        WorldBossRepository(session), PlayerRepository(session)
    ).execute(discord_id=1, username="alice", display_name="Alice")
    p_alice = session.query(PlayerModel).filter_by(discord_id=1).one().id

    # Pose le profil à level 1, xp 90 (presque level 2 si threshold ~100)
    from app.infrastructure.db.models.progression_model import PlayerProgressionModel
    prog = session.get(PlayerProgressionModel, p_alice)
    prog.xp = 90
    session.commit()

    # Donne des métriques pour qu'Alice soit top damage (cumul = 100xp + 25 base = 125xp)
    WorldBossRepository(session).add_combat_metrics(
        boss.id, p_alice, damage_dealt=500, damage_tanked=0, hp_healed=0,
    )

    complete = CompleteWorldBossUseCase(
        world_boss_repository=WorldBossRepository(session),
        player_repository=PlayerRepository(session),
        item_repository=ItemRepository(session),
        inventory_repository=InventoryRepository(session),
    )
    result = complete.execute(boss.id)
    assert result.success is True

    # Avec 90 + 125 = 215 xp, Alice doit avoir au moins level 2 et un skill_point
    refreshed = session.get(PlayerProgressionModel, p_alice)
    session.refresh(refreshed)
    assert refreshed.level >= 2
    assert refreshed.skill_points >= 1


def test_complete_distributes_rewards_to_top_and_base(session):
    _seed_mob(session)
    _seed_potions(session)
    SpawnWorldBossUseCase(
        WorldBossRepository(session),
    ).execute(boss_code="slime_titan")

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
