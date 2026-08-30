"""Cycle complet d'une commande d'artisan, en base.

Vérifie les règles qui font du travail d'artisan un vrai puits d'or :
  • les ingrédients ET l'or sont débités au lancement ;
  • un seul travail actif par artisan ;
  • rien n'est livré avant l'échéance ;
  • annuler rend les ingrédients et une partie de l'or ;
  • chaque travail RÉCUPÉRÉ fait monter la maîtrise.
"""

from datetime import datetime, timedelta, UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.artisan_work import ArtisanWorkUseCase
from app.domain.entities.artisan import ArtisanDefinition, MasteryTier, PricingRules
from app.domain.services.artisan_service import ArtisanService
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.player_model import PlayerModel  # noqa: F401
from app.infrastructure.db.models.progression_model import PlayerProgressionModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel  # noqa: F401
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel  # noqa: F401
from app.infrastructure.db.models.craft_model import (  # noqa: F401
    CraftRecipeIngredientModel,
    CraftRecipeModel,
)
from app.infrastructure.db.models.work_order_model import (  # noqa: F401
    PlayerArtisanMasteryModel,
    PlayerWorkOrderModel,
    STATUS_READY,
)
from app.infrastructure.db.repositories.craft_repository import CraftRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.work_order_repository import (
    WorkOrderRepository,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _forgeron(instant: bool = False) -> ArtisanDefinition:
    return ArtisanDefinition(
        code="forgeron", name="Borak", title="Forgeron", verb="forger",
        work_noun="forge", image="", categories=("arme",), greeting="",
        accent=(0, 0, 0),
        tiers=(
            MasteryTier(
                level=1, code="apprenti", name="Apprenti", orders_required=0,
                max_item_power=0, gold_discount_pct=0,
                duration_pct=0 if instant else 100,
            ),
        ),
    )


def _use_case(session) -> ArtisanWorkUseCase:
    return ArtisanWorkUseCase(
        player_repository=PlayerRepository(session),
        inventory_repository=InventoryRepository(session),
        item_repository=ItemRepository(session),
        craft_repository=CraftRepository(session),
        work_order_repository=WorkOrderRepository(session),
        artisan_service=ArtisanService(PricingRules()),
    )


def _item(session, code, category="arme", bonuses=None):
    item = ItemDefinitionModel(
        code=code, name=code.replace("_", " ").title(), description="",
        category=category, rarity="common", stackable=True, max_stack=99,
        sell_price=0, buy_price=0, icon="", stat_bonuses_json=bonuses or {},
        equipment_slot="arme" if category == "arme" else None,
        requires_two_hands=False, family="",
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(item)
    session.flush()
    return item


def _recipe(session, code, result_id, ingredients):
    recipe = CraftRecipeModel(
        code=code, name=code, result_item_definition_id=result_id,
        result_quantity=1,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    session.add(recipe)
    session.flush()
    for item_id, qty in ingredients:
        session.add(CraftRecipeIngredientModel(
            craft_recipe_id=recipe.id, item_definition_id=item_id, quantity=qty,
        ))
    session.flush()
    return recipe


@pytest.fixture()
def world(session):
    """Un joueur riche, un minerai, une épée, une recette."""
    profile = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=1, username="u", display_name="U",
    )
    pid = profile.player.id
    PlayerRepository(session).add_gold(pid, 5000)

    ore = _item(session, "minerai", category="resource")
    sword = _item(session, "epee", category="arme", bonuses={"attack": 12})
    recipe = _recipe(session, "epee_recipe", sword.id, [(ore.id, 3)])
    InventoryRepository(session).add_item(pid, ore.id, 10)
    session.commit()
    return {"pid": pid, "ore": ore, "sword": sword, "recipe": recipe}


def _gold(session, pid):
    return PlayerRepository(session).get_profile_by_player_id(pid).resources.gold


def _qty(session, pid, code):
    return next(
        (
            i.quantity
            for i in InventoryRepository(session).list_by_player_id(pid)
            if i.item_definition.code == code
        ),
        0,
    )


# ------------------------------------------------------------- commande --
def test_lancer_un_travail_debite_ingredients_et_or(session, world):
    pid = world["pid"]
    before_gold = _gold(session, pid)
    uc = _use_case(session)
    preview = uc.preview(_forgeron(), pid, "epee_recipe")

    result = uc.start(_forgeron(), pid, "epee_recipe")
    session.commit()

    assert result.success
    assert _qty(session, pid, "minerai") == 7  # 10 − 3
    assert _gold(session, pid) == before_gold - preview.quote.gold_cost
    # rien n'est livré tant que ce n'est pas récupéré
    assert _qty(session, pid, "epee") == 0


def test_un_seul_travail_actif_par_artisan(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    assert uc.start(_forgeron(), pid, "epee_recipe").success
    session.commit()

    second = uc.start(_forgeron(), pid, "epee_recipe")
    assert not second.success
    assert "déjà un travail en cours" in second.message


def test_refus_si_ingredients_insuffisants(session, world):
    pid = world["pid"]
    InventoryRepository(session).remove_item(pid, world["ore"].id, 9)
    session.commit()

    result = _use_case(session).start(_forgeron(), pid, "epee_recipe")
    assert not result.success
    assert "manquant" in result.message.lower()


def test_refus_si_or_insuffisant(session, world):
    pid = world["pid"]
    PlayerRepository(session).add_gold(pid, -_gold(session, pid))
    session.commit()

    result = _use_case(session).start(_forgeron(), pid, "epee_recipe")
    assert not result.success
    assert "or" in result.message.lower()


def test_refus_si_la_piece_depasse_le_palier(session, world):
    pid = world["pid"]
    bride = ArtisanDefinition(
        code="forgeron", name="B", title="F", verb="forger", work_noun="forge",
        image="", categories=("arme",), greeting="", accent=(0, 0, 0),
        tiers=(MasteryTier(1, "a", "Apprenti", 0, max_item_power=1,
                           gold_discount_pct=0, duration_pct=100),),
    )
    result = _use_case(session).start(bride, pid, "epee_recipe")
    assert not result.success
    assert "puissante" in result.message.lower()


# ------------------------------------------------------------ livraison --
def test_rien_n_est_livre_avant_l_echeance(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    uc.start(_forgeron(), pid, "epee_recipe")
    session.commit()

    result = uc.collect(_forgeron(), pid)
    assert not result.success
    assert _qty(session, pid, "epee") == 0


def test_travail_instantane_est_recuperable_tout_de_suite(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    uc.start(_forgeron(instant=True), pid, "epee_recipe")
    session.commit()

    result = uc.collect(_forgeron(instant=True), pid)
    session.commit()
    assert result.success
    assert _qty(session, pid, "epee") == 1


def test_l_echeance_atteinte_rend_le_travail_recuperable(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    uc.start(_forgeron(), pid, "epee_recipe")
    session.commit()

    # on force l'échéance dans le passé, comme le ferait le temps qui passe
    order = WorkOrderRepository(session).get_active(pid, "forgeron")
    order.ready_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()

    WorkOrderRepository(session).mark_ready_due()
    session.commit()

    assert uc.collect(_forgeron(), pid).success
    session.commit()
    assert _qty(session, pid, "epee") == 1


def test_recuperer_libere_l_artisan(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    uc.start(_forgeron(instant=True), pid, "epee_recipe")
    session.commit()
    uc.collect(_forgeron(instant=True), pid)
    session.commit()

    assert uc.start(_forgeron(instant=True), pid, "epee_recipe").success


# ------------------------------------------------------------- maîtrise --
def test_la_maitrise_monte_a_chaque_travail_recupere(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    repo = WorkOrderRepository(session)
    assert repo.orders_completed(pid, "forgeron") == 0

    for _ in range(3):
        uc.start(_forgeron(instant=True), pid, "epee_recipe")
        session.commit()
        uc.collect(_forgeron(instant=True), pid)
        session.commit()

    assert repo.orders_completed(pid, "forgeron") == 3


def test_un_travail_annule_ne_fait_pas_monter_la_maitrise(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    uc.start(_forgeron(), pid, "epee_recipe")
    session.commit()
    uc.cancel(_forgeron(), pid)
    session.commit()

    assert WorkOrderRepository(session).orders_completed(pid, "forgeron") == 0


# ------------------------------------------------------------ annulation --
def test_annuler_rend_les_ingredients_et_une_part_de_l_or(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    gold_before = _gold(session, pid)
    preview = uc.preview(_forgeron(), pid, "epee_recipe")
    cost = preview.quote.gold_cost

    uc.start(_forgeron(), pid, "epee_recipe")
    session.commit()
    result = uc.cancel(_forgeron(), pid)
    session.commit()

    assert result.success
    assert _qty(session, pid, "minerai") == 10  # ingrédients rendus
    # la moitié de l'or est perdue : l'artisan a entamé la matière
    assert _gold(session, pid) == gold_before - cost + round(cost * 0.5)


def test_annuler_libere_l_artisan(session, world):
    pid = world["pid"]
    uc = _use_case(session)
    uc.start(_forgeron(), pid, "epee_recipe")
    session.commit()
    uc.cancel(_forgeron(), pid)
    session.commit()

    assert uc.start(_forgeron(), pid, "epee_recipe").success


# ------------------------------------------------------- répartition PNJ --
def test_chaque_artisan_ne_voit_que_ses_categories(session, world):
    """Le forgeron ne propose pas les accessoires, et réciproquement."""
    pid = world["pid"]
    bague = _item(session, "bague", category="accessoire", bonuses={"defense": 2})
    _recipe(session, "bague_recipe", bague.id, [(world["ore"].id, 1)])
    session.commit()

    uc = _use_case(session)
    codes_forge = {r.code for r in uc.recipes_for(_forgeron())}
    assert codes_forge == {"epee_recipe"}

    artisane = ArtisanDefinition(
        code="artisan", name="Elna", title="Artisane", verb="confectionner",
        work_noun="confection", image="", categories=("accessoire",),
        greeting="", accent=(0, 0, 0),
        tiers=(MasteryTier(1, "a", "Apprentie", 0, 0, 0, 100),),
    )
    assert {r.code for r in uc.recipes_for(artisane)} == {"bague_recipe"}


def test_les_deux_artisans_travaillent_en_parallele(session, world):
    """Une forge ET une confection peuvent tourner en même temps."""
    pid = world["pid"]
    bague = _item(session, "bague", category="accessoire", bonuses={"defense": 2})
    _recipe(session, "bague_recipe", bague.id, [(world["ore"].id, 1)])
    session.commit()

    artisane = ArtisanDefinition(
        code="artisan", name="Elna", title="Artisane", verb="confectionner",
        work_noun="confection", image="", categories=("accessoire",),
        greeting="", accent=(0, 0, 0),
        tiers=(MasteryTier(1, "a", "Apprentie", 0, 0, 0, 100),),
    )
    uc = _use_case(session)
    assert uc.start(_forgeron(), pid, "epee_recipe").success
    session.commit()
    assert uc.start(artisane, pid, "bague_recipe").success
