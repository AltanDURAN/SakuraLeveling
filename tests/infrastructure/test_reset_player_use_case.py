"""Tests du ResetPlayerUseCase — vérifie que TOUTES les tables liées
au joueur sont purgées (1 test par table sensible)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.infrastructure.db.base import Base

from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel  # noqa: F401
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel
from app.infrastructure.db.models.craft_model import CraftRecipeModel, CraftRecipeIngredientModel  # noqa: F401
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel
from app.infrastructure.db.models.world_boss_model import WorldBossModel, WorldBossParticipationModel
from app.infrastructure.db.models.player_title_model import PlayerTitleModel
from app.infrastructure.db.models.weekly_quest_model import WeeklyQuestAssignmentModel
from app.infrastructure.db.models.daily_quest_model import DailyQuestAssignmentModel
from app.infrastructure.db.models.marketplace_listing_model import MarketplaceListingModel
from app.infrastructure.db.models.help_subscriber_model import HelpSubscriberModel


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


def _create_player(session, discord_id: int, name: str) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id, username=name.lower(), display_name=name,
        created_at=now, updated_at=now,
    )
    session.add(player)
    session.flush()
    session.add(
        PlayerProgressionModel(
            player_id=player.id, level=5, xp=100, skill_points=3,
            created_at=now, updated_at=now,
        )
    )
    session.add(
        PlayerResourceModel(
            player_id=player.id, gold=500, daily_streak=2,
            created_at=now, updated_at=now,
        )
    )
    session.commit()
    return player.id


def _seed_full_profile(session, player_id: int, other_player_id: int) -> None:
    """Crée une ligne dans CHAQUE table liée au joueur."""
    now = datetime.now(UTC)

    # Inventory : on a besoin d'un item
    item = ItemDefinitionModel(
        code="dummy", name="Dummy", description="",
        category="resource", rarity="common", stackable=True,
        max_stack=None, sell_price=1, buy_price=None,
        icon=None, stat_bonuses_json=None,
        equipment_slot=None, requires_two_hands=False,
        created_at=now, updated_at=now,
    )
    session.add(item)
    session.flush()

    session.add(PlayerInventoryItemModel(
        player_id=player_id, item_definition_id=item.id, quantity=5,
        created_at=now, updated_at=now,
    ))
    session.add(PlayerEquipmentItemModel(
        player_id=player_id, item_definition_id=item.id, slot="casque",
        created_at=now, updated_at=now,
    ))
    session.add(PlayerCooldownModel(
        player_id=player_id, action_key="daily",
        last_used_at=now, next_available_at=now,
    ))
    session.add(PlayerHealthStateModel(
        player_id=player_id, current_hp=42, updated_at=now,
    ))
    session.add(PlayerMobKillModel(
        player_id=player_id, mob_code="slime", kill_count=10,
    ))
    # PlayerProfessionModel a besoin d'une profession_definitions row
    from app.infrastructure.db.models.profession_model import ProfessionDefinitionModel
    prof_def = ProfessionDefinitionModel(
        code="mining", name="Mining", description="",
        created_at=now, updated_at=now,
    )
    session.add(prof_def)
    session.flush()
    session.add(PlayerProfessionModel(
        player_id=player_id, profession_definition_id=prof_def.id,
        level=2, xp=10,
        created_at=now, updated_at=now,
    ))
    session.add(PlayerCareerStatsModel(
        player_id=player_id, combats_fought=10,
        combats_won=5, combats_lost=5, gold_earned_total=500,
        damage_dealt_total=1000, damage_tanked_total=500, hp_healed_total=100,
        created_at=now, updated_at=now,
    ))
    session.add(PlayerSkillAllocationModel(
        player_id=player_id, skill_code="aventurier", level=1,
        created_at=now, updated_at=now,
    ))
    session.add(PlayerDuelRankModel(
        player_id=player_id, rank_position=1, wins=10, losses=2,
        created_at=now, updated_at=now,
    ))
    session.add(PlayerTitleModel(
        player_id=player_id, title_code="slime_slayer", is_active=True,
        unlocked_at=now,
    ))
    session.add(WeeklyQuestAssignmentModel(
        player_id=player_id, week_start=now,
        quest_code="kill_10_mobs", progress=5,
        completed=False, claimed=False,
        created_at=now, updated_at=now,
    ))
    session.add(DailyQuestAssignmentModel(
        player_id=player_id, day_start=now,
        quest_code="craft_3", progress=1,
        completed=False, claimed=False,
        created_at=now, updated_at=now,
    ))
    session.add(HelpSubscriberModel(
        player_id=player_id, subscribed_at=now,
    ))

    # World boss participation : besoin d'un boss
    boss = WorldBossModel(
        code="test_boss", name="Test Boss",
        image_name="",
        max_hp=1000, current_hp=1000,
        attack=50, defense=20, speed=10,
        crit_chance=10, crit_damage=150, dodge=5,
        hp_regeneration=0,
        status="active",
        spawned_at=now, defeated_at=None,
    )
    session.add(boss)
    session.flush()
    session.add(WorldBossParticipationModel(
        boss_id=boss.id, player_id=player_id,
        damage_dealt=100, damage_tanked=20, hp_healed=0,
        fights_count=1,
        created_at=now, updated_at=now,
    ))

    # Marketplace : annonce active du joueur + annonce vendue à un autre
    # joueur où player_id est le buyer
    session.add(MarketplaceListingModel(
        seller_player_id=player_id, item_definition_id=item.id, quantity=3,
        price_per_unit=10, status="active",
        last_buyer_player_id=None,
        listed_at=now, expires_at=now,
    ))
    session.add(MarketplaceListingModel(
        seller_player_id=other_player_id, item_definition_id=item.id, quantity=1,
        price_per_unit=5, status="sold",
        last_buyer_player_id=player_id,
        listed_at=now, expires_at=now, closed_at=now,
    ))

    # Trades : un comme initiator, un comme target
    trade1 = TradeModel(
        initiator_player_id=player_id, target_player_id=other_player_id,
        status="pending", initiator_gold_offered=100, target_gold_offered=0,
        expires_at=now, created_at=now, updated_at=now,
    )
    trade2 = TradeModel(
        initiator_player_id=other_player_id, target_player_id=player_id,
        status="pending", initiator_gold_offered=0, target_gold_offered=50,
        expires_at=now, created_at=now, updated_at=now,
    )
    session.add(trade1)
    session.add(trade2)
    session.flush()
    session.add(TradeItemModel(
        trade_id=trade1.id, offered_by="initiator",
        item_definition_id=item.id, quantity=1,
    ))
    session.add(TradeItemModel(
        trade_id=trade2.id, offered_by="target",
        item_definition_id=item.id, quantity=2,
    ))

    session.commit()


def test_reset_player_purges_all_player_tables(session):
    player_id = _create_player(session, discord_id=111, name="Alice")
    other_id = _create_player(session, discord_id=222, name="Bob")
    _seed_full_profile(session, player_id, other_id)

    ResetPlayerUseCase().execute(session, player_id)

    # Player conservé (identité Discord intacte)
    assert session.get(PlayerModel, player_id) is not None

    # Progression / Resource : remis à zéro mais ligne conservée
    prog = session.get(PlayerProgressionModel, player_id)
    assert prog is not None
    assert prog.level == 1 and prog.xp == 0 and prog.skill_points == 0
    res = session.get(PlayerResourceModel, player_id)
    assert res is not None
    assert res.gold == 0 and res.daily_streak == 0

    # Toutes les tables 1:N → 0 ligne pour ce joueur
    for model_cls in (
        PlayerInventoryItemModel,
        PlayerEquipmentItemModel,
        PlayerClassStateModel,
        PlayerQuestStateModel,
        PlayerCooldownModel,
        PlayerHealthStateModel,
        PlayerMobKillModel,
        PlayerProfessionModel,
        PlayerCareerStatsModel,
        PlayerSkillAllocationModel,
        PlayerDuelRankModel,
        WorldBossParticipationModel,
        PlayerTitleModel,
        WeeklyQuestAssignmentModel,
        DailyQuestAssignmentModel,
        HelpSubscriberModel,
    ):
        rows = session.execute(
            select(model_cls).where(model_cls.player_id == player_id)
        ).scalars().all()
        assert rows == [], f"{model_cls.__tablename__} a encore {len(rows)} ligne(s)"

    # Marketplace : annonces du joueur supprimées
    seller_listings = session.execute(
        select(MarketplaceListingModel).where(
            MarketplaceListingModel.seller_player_id == player_id
        )
    ).scalars().all()
    assert seller_listings == []

    # Marketplace : annonces sold où il était buyer → champ buyer NULL
    listings_with_buyer = session.execute(
        select(MarketplaceListingModel).where(
            MarketplaceListingModel.last_buyer_player_id == player_id
        )
    ).scalars().all()
    assert listings_with_buyer == []

    # Trades : tous les trades impliquant le joueur sont purgés
    from sqlalchemy import or_
    trades_remaining = session.execute(
        select(TradeModel).where(
            or_(
                TradeModel.initiator_player_id == player_id,
                TradeModel.target_player_id == player_id,
            )
        )
    ).scalars().all()
    assert trades_remaining == []

    # Et leurs trade_items aussi
    trade_items = session.execute(select(TradeItemModel)).scalars().all()
    assert trade_items == []


def test_reset_player_preserves_other_player_data(session):
    """Le reset d'un joueur ne doit PAS toucher aux données des autres joueurs."""
    p1 = _create_player(session, discord_id=111, name="Alice")
    p2 = _create_player(session, discord_id=222, name="Bob")

    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code="dummy2", name="Dummy", description="",
        category="resource", rarity="common", stackable=True,
        max_stack=None, sell_price=1, buy_price=None,
        icon=None, stat_bonuses_json=None,
        equipment_slot=None, requires_two_hands=False,
        created_at=now, updated_at=now,
    )
    session.add(item)
    session.flush()
    session.add(PlayerInventoryItemModel(
        player_id=p2, item_definition_id=item.id, quantity=42,
        created_at=now, updated_at=now,
    ))
    session.commit()

    ResetPlayerUseCase().execute(session, p1)

    # Bob doit garder son inventaire
    p2_inv = session.execute(
        select(PlayerInventoryItemModel).where(
            PlayerInventoryItemModel.player_id == p2
        )
    ).scalars().all()
    assert len(p2_inv) == 1
    assert p2_inv[0].quantity == 42
