"""Tests d'intégration de EquipItemUseCase (slots compatibles, 2-mains, etc.)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.equip_item import EquipItemUseCase
from app.infrastructure.db.base import Base

# Tous les modèles pour Base.metadata
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

from app.infrastructure.db.repositories.equipment_repository import EquipmentRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
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


def _create_player(session, discord_id: int = 1) -> int:
    now = datetime.now(UTC)
    player = PlayerModel(
        discord_id=discord_id,
        username="alpha",
        display_name="Alpha",
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    session.add(player)
    session.flush()

    session.add_all(
        [
            PlayerProgressionModel(
                player_id=player.id,
                level=1,
                xp=0,
                skill_points=0,
                created_at=now,
                updated_at=now,
            ),
            PlayerResourceModel(
                player_id=player.id,
                gold=0,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    session.commit()
    return player.id


def _create_item(
    session,
    code: str,
    name: str,
    category: str,
    equipment_slot: str | None,
    requires_two_hands: bool = False,
) -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code,
        name=name,
        description="",
        category=category,
        rarity="common",
        stackable=False,
        max_stack=None,
        sell_price=0,
        buy_price=None,
        icon=None,
        stat_bonuses_json=None,
        equipment_slot=equipment_slot,
        requires_two_hands=requires_two_hands,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def _give_item(session, player_id: int, item_definition_id: int, quantity: int = 1) -> None:
    now = datetime.now(UTC)
    session.add(
        PlayerInventoryItemModel(
            player_id=player_id,
            item_definition_id=item_definition_id,
            quantity=quantity,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()


def _make_use_case(session) -> EquipItemUseCase:
    return EquipItemUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        equipment_repository=EquipmentRepository(session),
    )


def test_equip_helmet_in_correct_slot(session):
    pid = _create_player(session)
    item_id = _create_item(session, "leather_cap", "Casque cuir", "helmet", "casque")
    _give_item(session, pid, item_id)

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", item_code="leather_cap"
    )

    assert result.success is True
    assert "casque" in result.slots_equipped


def test_equip_non_equipable_fails(session):
    pid = _create_player(session)
    item_id = _create_item(session, "slime_gel", "Gelée", "resource", None)
    _give_item(session, pid, item_id)

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", item_code="slime_gel"
    )

    assert result.success is False
    assert "équipable" in result.message.lower() or "equipable" in result.message.lower()


def test_equip_item_not_in_inventory_fails(session):
    _create_player(session)
    _create_item(session, "leather_cap", "Casque cuir", "helmet", "casque")
    # Pas de _give_item : l'item est défini mais pas dans l'inventaire

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", item_code="leather_cap"
    )

    assert result.success is False
    assert "inventaire" in result.message.lower()


def test_equip_helmet_in_wrong_slot_fails(session):
    pid = _create_player(session)
    item_id = _create_item(session, "leather_cap", "Casque cuir", "helmet", "casque")
    _give_item(session, pid, item_id)

    result = _make_use_case(session).execute(
        discord_id=1,
        username="alpha",
        display_name="Alpha",
        item_code="leather_cap",
        slot="bottes",
    )

    assert result.success is False


def test_equip_one_handed_weapon_in_main_hand_by_default(session):
    pid = _create_player(session)
    item_id = _create_item(session, "wood_sword", "Épée", "weapon", "main_droite")
    _give_item(session, pid, item_id)

    result = _make_use_case(session).execute(
        discord_id=1, username="alpha", display_name="Alpha", item_code="wood_sword"
    )

    assert result.success is True
    assert "main_droite" in result.slots_equipped


def test_equip_one_handed_weapon_in_off_hand(session):
    pid = _create_player(session)
    item_id = _create_item(session, "wood_sword", "Épée", "weapon", "main_droite")
    _give_item(session, pid, item_id)

    result = _make_use_case(session).execute(
        discord_id=1,
        username="alpha",
        display_name="Alpha",
        item_code="wood_sword",
        slot="main_gauche",
    )

    assert result.success is True
    assert "main_gauche" in result.slots_equipped


def test_equip_two_handed_takes_both_slots_and_unequips_offhand(session):
    pid = _create_player(session)
    sword_id = _create_item(
        session, "wood_sword", "Épée", "weapon", "main_droite"
    )
    shield_id = _create_item(
        session, "shield", "Bouclier", "shield", "main_gauche"
    )
    espadon_id = _create_item(
        session,
        "espadon",
        "Espadon",
        "weapon",
        "main_droite",
        requires_two_hands=True,
    )
    _give_item(session, pid, sword_id)
    _give_item(session, pid, shield_id)
    _give_item(session, pid, espadon_id)

    use_case = _make_use_case(session)
    use_case.execute(1, "alpha", "Alpha", "wood_sword", slot="main_droite")
    use_case.execute(1, "alpha", "Alpha", "shield", slot="main_gauche")

    # Équipe l'espadon : doit déséquiper l'épée ET le bouclier
    result = use_case.execute(1, "alpha", "Alpha", "espadon")

    assert result.success is True
    assert "main_droite" in result.slots_equipped
    assert "main_gauche" in result.slots_equipped
    assert "Épée" in result.unequipped_items
    assert "Bouclier" in result.unequipped_items

    # Vérification : main_gauche est maintenant vide en DB (l'espadon est en main_droite)
    repo = EquipmentRepository(session)
    assert repo.get_slot(pid, "main_droite").item_definition.code == "espadon"
    assert repo.get_slot(pid, "main_gauche") is None


def test_equip_in_off_hand_unequips_existing_two_handed(session):
    pid = _create_player(session)
    espadon_id = _create_item(
        session, "espadon", "Espadon", "weapon", "main_droite", requires_two_hands=True
    )
    shield_id = _create_item(
        session, "shield", "Bouclier", "shield", "main_gauche"
    )
    _give_item(session, pid, espadon_id)
    _give_item(session, pid, shield_id)

    use_case = _make_use_case(session)
    use_case.execute(1, "alpha", "Alpha", "espadon")

    # Équipe un bouclier en main_gauche : doit retirer l'espadon
    result = use_case.execute(1, "alpha", "Alpha", "shield", slot="main_gauche")

    assert result.success is True
    assert "Espadon" in result.unequipped_items

    repo = EquipmentRepository(session)
    assert repo.get_slot(pid, "main_droite") is None
    assert repo.get_slot(pid, "main_gauche").item_definition.code == "shield"


def test_equipping_replaces_existing_in_same_slot(session):
    pid = _create_player(session)
    cap_id = _create_item(session, "cap", "Casque cuir", "helmet", "casque")
    helmet_id = _create_item(session, "helm", "Casque fer", "helmet", "casque")
    _give_item(session, pid, cap_id)
    _give_item(session, pid, helmet_id)

    use_case = _make_use_case(session)
    use_case.execute(1, "alpha", "Alpha", "cap")
    result = use_case.execute(1, "alpha", "Alpha", "helm")

    assert result.success is True
    assert "Casque cuir" in result.unequipped_items
    repo = EquipmentRepository(session)
    assert repo.get_slot(pid, "casque").item_definition.code == "helm"


def test_equipping_same_one_handed_in_both_hands_requires_two_copies(session):
    pid = _create_player(session)
    dagger_id = _create_item(
        session, "dagger", "Dague", "weapon", "main_droite"
    )
    _give_item(session, pid, dagger_id, quantity=1)  # un seul exemplaire

    use_case = _make_use_case(session)
    use_case.execute(1, "alpha", "Alpha", "dagger", slot="main_droite")

    # Tenter d'équiper la même dague en main_gauche avec un seul exemplaire
    result = use_case.execute(1, "alpha", "Alpha", "dagger", slot="main_gauche")

    assert result.success is False
    assert "second" in result.message.lower() or "exemplaire" in result.message.lower()


def test_equipping_same_one_handed_with_two_copies_succeeds(session):
    pid = _create_player(session)
    dagger_id = _create_item(
        session, "dagger", "Dague", "weapon", "main_droite"
    )
    _give_item(session, pid, dagger_id, quantity=2)

    use_case = _make_use_case(session)
    use_case.execute(1, "alpha", "Alpha", "dagger", slot="main_droite")
    result = use_case.execute(1, "alpha", "Alpha", "dagger", slot="main_gauche")

    assert result.success is True
