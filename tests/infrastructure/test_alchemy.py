"""Elna, l'alchimiste : confection (ingrédients + or), potions de mana et
élixirs (un même effet se renouvelle, des effets différents s'additionnent, et
ils ne comptent qu'en combat de zone / world boss)."""

import random
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.application.services.encounter_service import EncounterService
from app.application.services.status_effect_resolver import resolve_status_effects
from app.application.use_cases.brew_potion import BrewPotionUseCase
from app.domain.entities.artisan import AlchemistDefinition, MasteryTier
from app.domain.services.alchemy_service import Recipe
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.player_mana_state_model import PlayerManaStateModel  # noqa: F401
from app.infrastructure.db.models.player_status_effect_model import PlayerStatusEffectModel
from app.infrastructure.db.models.work_order_model import PlayerArtisanMasteryModel  # noqa: F401
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_mana_repository import PlayerManaRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_status_effect_repository import (
    PlayerStatusEffectRepository,
)
from app.infrastructure.db.repositories.work_order_repository import WorkOrderRepository
from tests.infrastructure.test_use_consumable import _build_use_case, session  # noqa: F401

ELNA = AlchemistDefinition(
    code="alchimiste", name="Elna", title="Alchimiste", image="", greeting="", accent=(0, 0, 0),
    tiers=(MasteryTier(1, "a", "Apprentie", 0, 0, 0, 100),
           MasteryTier(2, "b", "Légendaire", 10, 0, 50, 100, bonus_pct=100)),
    recipes=(Recipe("potion_x", (("gel_e", 2),), fee_per_level=4),),
)


def _item(session, code, category="consumable", bonuses=None) -> int:
    now = datetime.now(UTC)
    item = ItemDefinitionModel(
        code=code, name=code, description="", category=category, rarity="common",
        stackable=True, max_stack=None, sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json=bonuses, equipment_slot=None, requires_two_hands=False,
        created_at=now, updated_at=now,
    )
    session.add(item)
    session.commit()
    return item.id


def _player(session, gold=1000):
    profile = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U")
    PlayerRepository(session).set_gold(profile.player.id, gold)
    return profile.player.id


def _qty(session, pid, item_id) -> int:
    row = session.execute(select(PlayerInventoryItemModel).where(
        PlayerInventoryItemModel.player_id == pid,
        PlayerInventoryItemModel.item_definition_id == item_id)).scalar_one_or_none()
    return row.quantity if row else 0


def test_elna_consomme_les_ingredients_et_l_or(session):
    gel, potion = _item(session, "gel_e", "resource"), _item(session, "potion_x")
    pid = _player(session)
    InventoryRepository(session).add_item(pid, gel, 7)
    use_case = BrewPotionUseCase(session, ELNA, random.Random(0))
    assert use_case.status(pid).recipe("potion_x").max_count == 3

    res = use_case.brew(pid, "potion_x", 3)
    assert res.success and res.gold == 12   # 4 or × niveau 1 × 3
    assert _qty(session, pid, gel) == 1 and _qty(session, pid, potion) == 3
    assert PlayerRepository(session).get_profile_by_player_id(pid).resources.gold == 988
    assert WorkOrderRepository(session).orders_completed(pid, "alchimiste") == 3


def test_sans_ingredients_rien_ne_bouge(session):
    gel, potion = _item(session, "gel_e", "resource"), _item(session, "potion_x")
    pid = _player(session)
    InventoryRepository(session).add_item(pid, gel, 3)
    res = BrewPotionUseCase(session, ELNA).brew(pid, "potion_x", 2)
    assert not res.success and "Il te manque" in res.message
    assert _qty(session, pid, gel) == 3 and _qty(session, pid, potion) == 0
    assert PlayerRepository(session).get_profile_by_player_id(pid).resources.gold == 1000


def test_une_alchimiste_legendaire_offre_des_potions(session):
    gel, potion = _item(session, "gel_e", "resource"), _item(session, "potion_x")
    pid = _player(session)
    WorkOrderRepository(session).increment_mastery(pid, "alchimiste", amount=10)
    InventoryRepository(session).add_item(pid, gel, 4)
    res = BrewPotionUseCase(session, ELNA, random.Random(0)).brew(pid, "potion_x", 2)
    assert res.bonus == 2 and _qty(session, pid, potion) == 4
    assert res.gold == 4   # remise de 50 %


def test_potion_de_mana(session):
    mana = _item(session, "potion_mana", bonuses={"effect": "mana_percent", "value": 50})
    pid = _player(session)
    InventoryRepository(session).add_item(pid, mana, 2)
    repo = PlayerManaRepository(session)
    repo.get_or_create(pid, default_current_mana=100)
    repo.update_current_mana(pid, 10)
    res = _build_use_case(session).execute(1, "u", "U", "potion_mana")
    assert res.success and repo.get_by_player_id(pid).current_mana == 60
    repo.update_current_mana(pid, 100)
    full = _build_use_case(session).execute(1, "u", "U", "potion_mana")
    assert not full.success and _qty(session, pid, mana) == 1   # pas gâchée


def test_un_meme_elixir_se_renouvelle_des_elixirs_differents_s_additionnent(session):
    force = _item(session, "elixir_force", bonuses={"effect": "elixir", "kind": "attack", "value": 10, "minutes": 60})
    garde = _item(session, "elixir_garde", bonuses={"effect": "elixir", "kind": "defense", "value": 10, "minutes": 60})
    pid = _player(session)
    InventoryRepository(session).add_item(pid, force, 2)
    InventoryRepository(session).add_item(pid, garde, 1)
    use_case = _build_use_case(session)
    assert use_case.execute(1, "u", "U", "elixir_force").success
    again = use_case.execute(1, "u", "U", "elixir_force")
    assert again.success and "repart à zéro" in again.message
    assert use_case.execute(1, "u", "U", "elixir_garde").success

    rows = session.execute(select(PlayerStatusEffectModel).where(
        PlayerStatusEffectModel.player_id == pid)).scalars().all()
    assert sorted(r.kind for r in rows) == ["elixir_attack", "elixir_defense"]   # pas de doublon

    field = resolve_status_effects(session, pid, elixirs=True)
    assert round(field.attack_percent, 6) == 0.10 and round(field.defense_percent, 6) == 0.10
    # Hors terrain (épreuves, défis, rang affiché) : rien.
    elsewhere = resolve_status_effects(session, pid)
    assert elsewhere.attack_percent == 0 and elsewhere.defense_percent == 0
    # Et un élixir n'est jamais pris pour un effet « toutes stats » d'événement.
    assert PlayerStatusEffectRepository(session).list_active_multipliers(pid) == []


def test_vitalite_garde_la_proportion_des_pv():
    assert EncounterService._scaled_hp(500, 1000, 1100) == 550
    assert EncounterService._scaled_hp(550, 1100, 1000) == 500
    assert EncounterService._scaled_hp(1000, 1000, 1000) == 1000
