from datetime import datetime, UTC, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.claim_daily_reward import ClaimDailyRewardUseCase
from app.domain.services.cooldown_service import CooldownService
from app.infrastructure.db.base import Base

# Imports nécessaires pour enregistrer toutes les tables dans Base.metadata
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel  # noqa: F401
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.craft_model import CraftRecipeModel, CraftRecipeIngredientModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel  # noqa: F401
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_model import PlayerModel  # noqa: F401
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel

from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository


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


def _make_use_case(session) -> ClaimDailyRewardUseCase:
    return ClaimDailyRewardUseCase(
        player_repository=PlayerRepository(session),
        cooldown_repository=CooldownRepository(session),
        cooldown_service=CooldownService(),
    )


def _force_cooldown_expiry(session, player_id: int) -> None:
    """Recule le next_available_at du daily pour permettre une nouvelle réclamation."""
    cooldown = (
        session.query(PlayerCooldownModel)
        .filter_by(player_id=player_id, action_key="daily")
        .one_or_none()
    )
    if cooldown is not None:
        cooldown.next_available_at = datetime.now(UTC) - timedelta(hours=1)
        session.commit()


def test_first_daily_returns_streak_1_and_100_gold(session):
    use_case = _make_use_case(session)

    result = use_case.execute(
        discord_id=1,
        username="alpha",
        display_name="Alpha",
    )

    assert result.success is True
    assert result.streak == 1
    assert result.gold_gained == 100


def test_second_daily_after_cooldown_returns_streak_2_and_200_gold(session):
    use_case = _make_use_case(session)

    # 1er daily
    result_1 = use_case.execute(discord_id=1, username="alpha", display_name="Alpha")
    assert result_1.streak == 1

    # Force l'expiration du cooldown
    profile = PlayerRepository(session).get_by_discord_id(1)
    _force_cooldown_expiry(session, profile.player.id)

    # 2e daily
    result_2 = use_case.execute(discord_id=1, username="alpha", display_name="Alpha")

    assert result_2.success is True
    assert result_2.streak == 2
    assert result_2.gold_gained == 200


def test_streak_keeps_growing_across_multiple_claims(session):
    use_case = _make_use_case(session)
    expected_total_gold = 0

    for expected_streak in range(1, 6):
        result = use_case.execute(discord_id=1, username="alpha", display_name="Alpha")
        assert result.success is True
        assert result.streak == expected_streak
        assert result.gold_gained == expected_streak * 100
        expected_total_gold += result.gold_gained
        profile = PlayerRepository(session).get_by_discord_id(1)
        _force_cooldown_expiry(session, profile.player.id)

    profile = PlayerRepository(session).get_by_discord_id(1)
    assert profile.resources.gold == expected_total_gold
    assert profile.resources.daily_streak == 5


def test_daily_during_cooldown_returns_failure_with_current_streak(session):
    use_case = _make_use_case(session)

    use_case.execute(discord_id=1, username="alpha", display_name="Alpha")
    second_attempt = use_case.execute(
        discord_id=1, username="alpha", display_name="Alpha"
    )

    assert second_attempt.success is False
    assert second_attempt.streak == 1  # série inchangée
    assert second_attempt.gold_gained == 0
    assert second_attempt.next_available_at is not None


def test_daily_does_not_grant_xp_anymore(session):
    use_case = _make_use_case(session)

    result = use_case.execute(discord_id=1, username="alpha", display_name="Alpha")

    profile = PlayerRepository(session).get_by_discord_id(1)
    assert result.success is True
    # XP doit rester à 0, le daily ne donne plus que de l'or
    assert profile.progression.xp == 0
    assert profile.progression.level == 1


def test_streak_persists_after_skipped_day_simulation(session):
    """La série ne reset jamais, même si le joueur saute des jours.

    On simule un saut de 3 jours en avançant artificiellement le cooldown
    à plusieurs jours dans le passé (au-delà du délai normal).
    """
    use_case = _make_use_case(session)

    use_case.execute(discord_id=1, username="alpha", display_name="Alpha")

    profile = PlayerRepository(session).get_by_discord_id(1)
    cooldown = (
        session.query(PlayerCooldownModel)
        .filter_by(player_id=profile.player.id, action_key="daily")
        .one()
    )
    cooldown.next_available_at = datetime.now(UTC) - timedelta(days=3)
    session.commit()

    result = use_case.execute(discord_id=1, username="alpha", display_name="Alpha")

    # Streak = 2 (et pas reset à 1) malgré 3 jours sans /daily
    assert result.success is True
    assert result.streak == 2
    assert result.gold_gained == 200
