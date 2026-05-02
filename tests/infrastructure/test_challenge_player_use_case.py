"""Tests d'intégration du ChallengePlayerUseCase (commande /fight @target).

Vérifie les règles métier :
    - Refus si auto-défi
    - Refus si la cible n'a pas de profil
    - Refus si challenger mieux classé (ou ex-aequo) que la cible
    - Cooldown 60s posé après un défi
    - Si challenger gagne → swap des positions + wins/losses incrémentés
    - Si challenger perd → positions inchangées + losses+1 challenger / wins+1 cible
    - HP réels (player_health_state) intouchés après le duel
"""

import random
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.challenge_player import (
    ChallengePlayerUseCase,
    DUEL_COOLDOWN_KEY,
)
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.duel_combat_service import DuelCombatService
from app.domain.services.stats_service import StatsService
from app.infrastructure.db.base import Base

# Imports nécessaires pour Base.metadata
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel  # noqa: F401
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.equipment_model import PlayerEquipmentItemModel  # noqa: F401
from app.infrastructure.db.models.mob_model import MobDefinitionModel  # noqa: F401
from app.infrastructure.db.models.class_model import ClassDefinitionModel  # noqa: F401
from app.infrastructure.db.models.player_class_state_model import PlayerClassStateModel  # noqa: F401
from app.infrastructure.db.models.craft_model import CraftRecipeModel, CraftRecipeIngredientModel  # noqa: F401
from app.infrastructure.db.models.cooldown_model import PlayerCooldownModel  # noqa: F401
from app.infrastructure.db.models.quest_model import QuestDefinitionModel, PlayerQuestStateModel  # noqa: F401
from app.infrastructure.db.models.profession_model import PlayerProfessionModel  # noqa: F401
from app.infrastructure.db.models.player_health_state_model import PlayerHealthStateModel
from app.infrastructure.db.models.player_mob_kill_model import PlayerMobKillModel  # noqa: F401
from app.infrastructure.db.models.shop_item_model import ShopItemModel  # noqa: F401
from app.infrastructure.db.models.player_career_stats_model import PlayerCareerStatsModel  # noqa: F401
from app.infrastructure.db.models.player_skill_allocation_model import PlayerSkillAllocationModel  # noqa: F401
from app.infrastructure.db.models.trade_model import TradeItemModel, TradeModel  # noqa: F401
from app.infrastructure.db.models.player_duel_rank_model import PlayerDuelRankModel  # noqa: F401

from app.infrastructure.db.repositories.class_repository import ClassRepository
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.player_duel_rank_repository import (
    PlayerDuelRankRepository,
)
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)


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


def _create_player(
    session,
    discord_id: int,
    name: str,
    level: int = 1,
    attack: int = 10,
) -> int:
    """Crée un joueur avec progression et ressources. Le `level` détermine
    la base de stats via StatsService (level → max_hp, attack via ProgressionService)."""
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id, username=name.lower(), display_name=name,
        created_at=now, updated_at=now, last_seen_at=now,
    )
    session.add(player)
    session.flush()

    session.add_all([
        PlayerProgressionModel(
            player_id=player.id, level=level, xp=0, skill_points=0,
            created_at=now, updated_at=now,
        ),
        PlayerResourceModel(
            player_id=player.id, gold=0, daily_streak=0,
            created_at=now, updated_at=now,
        ),
    ])
    session.commit()
    return player.id


def _build_use_case(session):
    return ChallengePlayerUseCase(
        player_repository=PlayerRepository(session),
        equipment_repository=EquipmentRepository(session),
        class_repository=ClassRepository(session),
        skill_allocation_repository=PlayerSkillAllocationRepository(session),
        duel_rank_repository=PlayerDuelRankRepository(session),
        cooldown_repository=CooldownRepository(session),
        stats_service=StatsService(),
        duel_combat_service=DuelCombatService(),
        cooldown_service=CooldownService(),
    )


def test_self_challenge_is_refused(session):
    _create_player(session, 1, "Alice")
    use_case = _build_use_case(session)

    outcome = use_case.execute(
        challenger_discord_id=1, challenger_username="alice",
        challenger_display_name="Alice",
        target_discord_id=1, target_display_name="Alice",
    )

    assert outcome.success is False
    assert "vous-même" in outcome.message


def test_target_without_profile_is_refused(session):
    _create_player(session, 1, "Alice")
    use_case = _build_use_case(session)

    outcome = use_case.execute(
        challenger_discord_id=1, challenger_username="alice",
        challenger_display_name="Alice",
        target_discord_id=999, target_display_name="Ghost",
    )

    assert outcome.success is False
    assert "profil joueur" in outcome.message


def test_better_ranked_challenger_is_refused(session):
    """Alice est #1, Bob est #2. Alice ne peut pas défier Bob (elle est mieux classée)."""
    _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob")
    use_case = _build_use_case(session)

    # Premier défi de Bob → Alice : Bob #2, Alice #1 (auto-inscription)
    # Pour mettre Alice mieux classée, c'est le cas par défaut (1 < 2)
    repo = PlayerDuelRankRepository(session)
    p_alice = repo.get_or_create(_get_player_id(session, 1))  # pos 1
    p_bob = repo.get_or_create(_get_player_id(session, 2))    # pos 2
    assert p_alice.rank_position == 1
    assert p_bob.rank_position == 2

    # Alice (challenger #1) défie Bob (#2) → refus
    outcome = use_case.execute(
        challenger_discord_id=1, challenger_username="alice",
        challenger_display_name="Alice",
        target_discord_id=2, target_display_name="Bob",
    )

    assert outcome.success is False
    assert "mieux classé" in outcome.message


def test_weaker_challenger_wins_swaps_positions(session):
    """Bob (challenger #2, faible) bat Alice (#1, faible aussi mais...) → swap."""
    random.seed(0)
    _create_player(session, 1, "Alice")  # level 1, faible
    _create_player(session, 2, "Bob", level=50)  # level 50, beaucoup plus fort

    repo = PlayerDuelRankRepository(session)
    repo.get_or_create(_get_player_id(session, 1))  # Alice #1
    repo.get_or_create(_get_player_id(session, 2))  # Bob #2

    use_case = _build_use_case(session)
    outcome = use_case.execute(
        challenger_discord_id=2, challenger_username="bob",
        challenger_display_name="Bob",
        target_discord_id=1, target_display_name="Alice",
    )

    assert outcome.success is True
    assert outcome.challenger_won is True
    assert outcome.swapped is True
    assert outcome.challenger_old_position == 2
    assert outcome.challenger_new_position == 1
    assert outcome.target_old_position == 1
    assert outcome.target_new_position == 2

    # Vérification persistée
    assert repo.get_by_player_id(_get_player_id(session, 2)).rank_position == 1
    assert repo.get_by_player_id(_get_player_id(session, 1)).rank_position == 2
    # Wins/losses incrémentés
    assert repo.get_by_player_id(_get_player_id(session, 2)).wins == 1
    assert repo.get_by_player_id(_get_player_id(session, 1)).losses == 1


def test_weaker_challenger_loses_keeps_positions(session):
    """Bob (challenger #2, faible) défie Alice (#1, très forte) → Alice gagne, ladder inchangé."""
    random.seed(0)
    _create_player(session, 1, "Alice", level=50)  # forte
    _create_player(session, 2, "Bob")  # faible

    repo = PlayerDuelRankRepository(session)
    repo.get_or_create(_get_player_id(session, 1))  # Alice #1
    repo.get_or_create(_get_player_id(session, 2))  # Bob #2

    use_case = _build_use_case(session)
    outcome = use_case.execute(
        challenger_discord_id=2, challenger_username="bob",
        challenger_display_name="Bob",
        target_discord_id=1, target_display_name="Alice",
    )

    assert outcome.success is True
    assert outcome.challenger_won is False
    assert outcome.swapped is False
    assert outcome.challenger_new_position == 2
    assert outcome.target_new_position == 1

    # Wins/losses : Alice +1 win, Bob +1 loss
    assert repo.get_by_player_id(_get_player_id(session, 1)).wins == 1
    assert repo.get_by_player_id(_get_player_id(session, 2)).losses == 1


def test_cooldown_blocks_second_challenge_within_60s(session):
    random.seed(0)
    _create_player(session, 1, "Alice", level=50)
    _create_player(session, 2, "Bob")

    repo = PlayerDuelRankRepository(session)
    repo.get_or_create(_get_player_id(session, 1))
    repo.get_or_create(_get_player_id(session, 2))

    use_case = _build_use_case(session)

    first = use_case.execute(
        challenger_discord_id=2, challenger_username="bob",
        challenger_display_name="Bob",
        target_discord_id=1, target_display_name="Alice",
    )
    assert first.success is True

    # Second challenge tout de suite → refusé par le cooldown
    second = use_case.execute(
        challenger_discord_id=2, challenger_username="bob",
        challenger_display_name="Bob",
        target_discord_id=1, target_display_name="Alice",
    )
    assert second.success is False
    assert "attendre" in second.message.lower() or "<t:" in second.message


def test_duel_does_not_touch_player_health_state(session):
    """Spec : aucun PV réel n'est perdu après un duel. La table player_health_state
    n'est ni lue ni écrite par le use case. Ici on s'en assure en vérifiant
    qu'aucune ligne n'est créée pour les deux combattants."""
    random.seed(0)
    _create_player(session, 1, "Alice", level=50)
    _create_player(session, 2, "Bob")

    repo = PlayerDuelRankRepository(session)
    p_alice_id = _get_player_id(session, 1)
    p_bob_id = _get_player_id(session, 2)
    repo.get_or_create(p_alice_id)
    repo.get_or_create(p_bob_id)

    use_case = _build_use_case(session)
    use_case.execute(
        challenger_discord_id=2, challenger_username="bob",
        challenger_display_name="Bob",
        target_discord_id=1, target_display_name="Alice",
    )

    # Aucune ligne player_health_state créée pour les duellistes
    assert session.get(PlayerHealthStateModel, p_alice_id) is None
    assert session.get(PlayerHealthStateModel, p_bob_id) is None


def test_first_challenge_auto_inscribes_both_players_at_bottom(session):
    """Spec : le get_or_create attribue la prochaine position libre.
    Premier défi entre deux joueurs jamais inscrits → l'un est #1, l'autre #2."""
    random.seed(0)
    _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob", level=50)

    use_case = _build_use_case(session)
    # Avant : aucun n'est dans le ladder
    repo = PlayerDuelRankRepository(session)
    assert repo.get_by_player_id(_get_player_id(session, 1)) is None
    assert repo.get_by_player_id(_get_player_id(session, 2)) is None

    # On veut tester un cas où Bob est challenger. Pour qu'il soit moins bien
    # classé que Alice à l'inscription, il faut qu'Alice soit inscrite EN PREMIER.
    # → on simule en l'inscrivant manuellement avant
    repo.get_or_create(_get_player_id(session, 1))  # Alice #1
    # Bob sera auto-inscrit en #2 par le use case lors de son défi

    outcome = use_case.execute(
        challenger_discord_id=2, challenger_username="bob",
        challenger_display_name="Bob",
        target_discord_id=1, target_display_name="Alice",
    )

    assert outcome.success is True
    # Bob inscrit
    assert repo.get_by_player_id(_get_player_id(session, 2)) is not None


# ---------- Helpers ----------


def _get_player_id(session, discord_id: int) -> int:
    return session.query(PlayerModel).filter_by(discord_id=discord_id).one().id
