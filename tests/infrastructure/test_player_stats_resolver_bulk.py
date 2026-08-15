"""Non-régression du resolver EN LOT (`resolve_player_stats_bulk`).

Le leaderboard faisait du N+1 (≈6 requêtes par joueur, cf. audit §5). Le
resolver en lot doit produire des Stats **strictement identiques** à l'appel
unitaire, avec un nombre de requêtes constant.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.application.services.player_stats_resolver import (
    resolve_player_stats,
    resolve_player_stats_bulk,
)
from app.infrastructure.db.base import Base

# Imports nécessaires pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel  # noqa: F401
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
from app.infrastructure.db.models.player_title_model import PlayerTitleModel  # noqa: F401
from app.infrastructure.db.models.player_status_effect_model import PlayerStatusEffectModel  # noqa: F401
from app.infrastructure.db.models.player_item_level_model import PlayerItemLevelModel  # noqa: F401

from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_item_level_repository import (
    PlayerItemLevelRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.player_status_effect_repository import (
    PlayerStatusEffectRepository,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _make_item(session, code: str, bonuses: dict) -> ItemDefinitionModel:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code, name=code, description="", category="weapon", rarity="common",
        stackable=False, max_stack=None, sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json=bonuses, equipment_slot="main_droite",
        requires_two_hands=False, created_at=now, updated_at=now,
    )
    session.add(item)
    session.commit()
    return item


def _seed_players(session, n: int) -> list:
    """n joueurs, chacun avec une combinaison différente de bonus pour que
    l'égalité lot/unitaire soit significative (équipement, forge, buff…)."""
    repo = PlayerRepository(session)
    sword = _make_item(session, "epee_test", {"attack": 10, "max_hp": 20})
    profiles = []
    for i in range(n):
        prof = repo.get_or_create_by_discord_id(
            discord_id=1000 + i, username=f"u{i}", display_name=f"U{i}",
        )
        pid = prof.player.id
        if i % 2 == 0:  # la moitié équipe l'épée
            EquipmentRepository(session).equip_item(pid, sword.id, "main_droite")
        if i % 3 == 0:  # un tiers a une épée forgée
            PlayerItemLevelRepository(session).increment(pid, sword.id, 10)
        if i % 4 == 0:  # un quart a un buff actif
            PlayerStatusEffectRepository(session).add(pid, "test", 1.1, 3600)
        if i % 5 == 0:  # un cinquième a des points d'arbre
            PlayerSkillAllocationRepository(session).upsert_level(pid, "atk_flat_1", 1)
        session.commit()
        profiles.append(repo.get_profile_by_player_id(pid))
    return profiles


def test_bulk_matches_unit_resolver(session):
    """Même résultat, joueur par joueur, que l'appel unitaire."""
    profiles = _seed_players(session, 6)

    bulk = resolve_player_stats_bulk(session, profiles)

    for prof in profiles:
        pid = prof.player.id
        expected = resolve_player_stats(
            session=session,
            profile=prof,
            equipped_items=EquipmentRepository(session).list_by_player_id(pid),
            active_class=ClassRepository(session).get_current_class_for_player(pid),
        )
        assert bulk[pid] == expected, f"divergence pour le joueur {pid}"


def test_bulk_query_count_is_constant(session):
    """Le nombre de requêtes ne doit PAS croître avec le nombre de joueurs."""
    profiles = _seed_players(session, 8)
    engine = session.get_bind()

    counter = {"n": 0}

    def _count(conn, cursor, statement, params, context, executemany):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        counter["n"] = 0
        resolve_player_stats_bulk(session, profiles[:2])
        few = counter["n"]

        counter["n"] = 0
        resolve_player_stats_bulk(session, profiles)
        many = counter["n"]
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    # 2 joueurs vs 8 joueurs : même nombre de requêtes (constant).
    assert few == many, f"{few} requêtes pour 2 joueurs vs {many} pour 8 (N+1 !)"
    assert many <= 10, f"{many} requêtes : trop pour un resolver en lot"


def test_bulk_empty_returns_empty(session):
    assert resolve_player_stats_bulk(session, []) == {}
