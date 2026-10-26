"""L'étal de Sorn (26/10/2026) : prix fixes ou selon le niveau, un exemplaire
au plus, et les effets de ses outils (cor, sceau, parchemin, jeton, sablier)
— plus les cosmétiques portés sur /profil."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.application.services.cosmetic_resolver import worn_cosmetics
from app.application.use_cases.buy_from_shop import BuyFromShopUseCase
from app.application.use_cases.claim_daily_reward import ClaimDailyRewardUseCase
from app.application.use_cases.use_consumable import UseContext
from app.domain.services.cooldown_service import CooldownService
from app.domain.services.merchant_items import missed_after_guard
from app.domain.services.shop_pricing_service import ShopPricingService
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.models.item_model import ItemDefinitionModel
from app.infrastructure.db.models.mob_model import MobDefinitionModel
from app.infrastructure.db.models.player_cosmetic_model import PlayerCosmeticModel  # noqa: F401
from app.infrastructure.db.models.player_mana_state_model import PlayerManaStateModel  # noqa: F401
from app.infrastructure.db.models.player_status_effect_model import PlayerStatusEffectModel  # noqa: F401
from app.infrastructure.db.models.player_title_model import PlayerTitleModel  # noqa: F401
from app.infrastructure.db.models.work_order_model import PlayerArtisanMasteryModel  # noqa: F401
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_cosmetic_repository import PlayerCosmeticRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_skill_allocation_repository import (
    PlayerSkillAllocationRepository,
)
from app.infrastructure.db.repositories.shop_repository import ShopRepository
from tests.infrastructure.test_use_consumable import _build_use_case, session  # noqa: F401

NOW = datetime.now(UTC)


def _item(session, code, category="consumable", bonuses=None) -> int:
    item = ItemDefinitionModel(
        code=code, name=code, description="", category=category, rarity="common",
        stackable=True, max_stack=None, sell_price=0, buy_price=None, icon=None,
        stat_bonuses_json=bonuses, equipment_slot=None, requires_two_hands=False,
        created_at=NOW, updated_at=NOW,
    )
    session.add(item)
    session.commit()
    return item.id


def _player(session, gold=100_000, level=40):
    from app.infrastructure.db.models.progression_model import PlayerProgressionModel

    profile = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U")
    PlayerRepository(session).set_gold(profile.player.id, gold)
    progression = session.get(PlayerProgressionModel, profile.player.id)
    progression.level = level
    session.commit()
    return profile.player.id


def _qty(session, pid, item_id) -> int:
    row = session.execute(select(PlayerInventoryItemModel).where(
        PlayerInventoryItemModel.player_id == pid,
        PlayerInventoryItemModel.item_definition_id == item_id)).scalar_one_or_none()
    return row.quantity if row else 0


def _buy(session, code, quantity=1):
    return BuyFromShopUseCase(PlayerRepository(session), InventoryRepository(session),
                              ShopRepository(session), ShopPricingService()).execute(1, "u", "U", code, quantity)


def _use(session, code, rank="F", summon=None):
    return _build_use_case(session).execute(1, "u", "U", code, UseContext(player_rank=rank, summon_elite=summon))


# ------------------------------------------------------------------ étal --
def test_prix_selon_le_niveau_et_un_seul_exemplaire(session):
    scroll = _item(session, "parchemin_oubli", bonuses={"effect": "respec_stats"})
    ShopRepository(session).create(scroll, buy_price=0, max_sell_price=0, min_sell_price=0,
                                   stock_threshold=100, price_per_level=150, max_owned=1)
    pid = _player(session, gold=100_000, level=40)
    assert not _buy(session, "parchemin_oubli", 2).success            # un seul à la fois
    first = _buy(session, "parchemin_oubli")
    assert first.success and first.total_cost == 6000                 # 150 × niveau 40
    again = _buy(session, "parchemin_oubli")
    assert not again.success and "déjà" in again.message
    assert _qty(session, pid, scroll) == 1


def test_prix_fixe_identique_pour_tous(session):
    horn = _item(session, "cor_chasse_f", bonuses={"effect": "summon_elite", "rank": "F"})
    ShopRepository(session).create(horn, buy_price=1000, max_sell_price=0, min_sell_price=0, stock_threshold=100)
    _player(session, level=90)
    assert _buy(session, "cor_chasse_f", 2).total_cost == 2000


# --------------------------------------------------------------- outils --
def test_parchemin_d_oubli_reprend_tous_les_points(session):
    from app.infrastructure.db.models.progression_model import PlayerProgressionModel

    scroll = _item(session, "parchemin_oubli", bonuses={"effect": "respec_stats"})
    pid = _player(session)
    progression = session.get(PlayerProgressionModel, pid)
    progression.points_attack, progression.points_defense, progression.points_max_hp = 10, 5, 4
    progression.stat_points = 1
    session.commit()
    InventoryRepository(session).add_item(pid, scroll, 1)
    res = _use(session, "parchemin_oubli")
    assert res.success and "19 points" in res.message
    session.refresh(progression)
    assert progression.stat_points == 20 and progression.points_attack == 0
    assert _qty(session, pid, scroll) == 0


def test_jeton_d_arbre_garde_le_reset_gratuit(session):
    from app.infrastructure.skill_tree.skill_tree_loader import get_definition

    token = _item(session, "jeton_arbre", bonuses={"effect": "reset_tree"})
    pid = _player(session)
    node = next(n for n in get_definition() if not n.start and n.costs)
    PlayerSkillAllocationRepository(session).upsert_level(pid, node.code, 1)
    InventoryRepository(session).add_item(pid, token, 1)

    free = _use(session, "jeton_arbre")
    assert not free.success and "gratuit" in free.message and _qty(session, pid, token) == 1

    cooldowns = CooldownRepository(session)
    cooldowns.upsert(pid, "skill_tree_reset", last_used_at=NOW, next_available_at=NOW + timedelta(days=3))
    res = _use(session, "jeton_arbre")
    assert res.success and _qty(session, pid, token) == 0
    assert PlayerSkillAllocationRepository(session).list_by_player(pid) == {}
    # L'attente du reset gratuit n'a pas bougé.
    assert cooldowns.get_by_player_and_action(pid, "skill_tree_reset").next_available_at.replace(
        tzinfo=UTC) > NOW + timedelta(days=2)


def test_sceau_du_second_souffle(session):
    seal = _item(session, "sceau_souffle_e", bonuses={"effect": "trial_retry", "rank": "E"})
    pid = _player(session)
    InventoryRepository(session).add_item(pid, seal, 1)
    assert not _use(session, "sceau_souffle_e", rank="F").success      # pas d'échec à effacer
    cooldowns = CooldownRepository(session)
    cooldowns.upsert(pid, "rank_trial", last_used_at=NOW, next_available_at=NOW + timedelta(hours=5))
    wrong = _use(session, "sceau_souffle_e", rank="E")                  # sa prochaine épreuve : D
    assert not wrong.success and "rang **D**" in wrong.message
    res = _use(session, "sceau_souffle_e", rank="F")
    assert res.success and _qty(session, pid, seal) == 0
    until = cooldowns.get_by_player_and_action(pid, "rank_trial").next_available_at.replace(tzinfo=UTC)
    assert until <= datetime.now(UTC)


def test_cor_de_chasse(session):
    horn = _item(session, "cor_chasse_f", bonuses={"effect": "summon_elite", "rank": "F"})
    session.add(MobDefinitionModel(
        code="gobelin_superieur", name="Gobelin supérieur", description="", image_name="", family="gobelin",
        max_hp=1, current_hp=1, attack=1, defense=1, speed=1, crit_chance=0, crit_damage=100, dodge=0,
        hp_regeneration=0, xp_reward=200, gold_reward=1, spawn_weight=1, loot_table_json=None,
        created_at=NOW, updated_at=NOW))
    session.commit()
    pid = _player(session)
    InventoryRepository(session).add_item(pid, horn, 2)
    calls = []

    def summon(code, channel):
        calls.append((code, channel))
        return True, "arrive dans quelques secondes"

    res = _use(session, "cor_chasse_f", rank="F", summon=summon)
    assert res.success and calls[0][0] == "gobelin_superieur" and res.announce_channel_id == calls[0][1]
    assert _qty(session, pid, horn) == 1
    again = _use(session, "cor_chasse_f", rank="F", summon=summon)
    assert not again.success and "souffle court" in again.message and len(calls) == 1


def test_cor_d_une_zone_inaccessible(session):
    horn = _item(session, "cor_chasse_d", bonuses={"effect": "summon_elite", "rank": "D"})
    pid = _player(session)
    InventoryRepository(session).add_item(pid, horn, 1)
    res = _use(session, "cor_chasse_d", rank="E", summon=lambda c, ch: (True, ""))
    assert not res.success and "rang **D**" in res.message and _qty(session, pid, horn) == 1


def test_sablier_pardonne_un_jour_manque(session):
    guard = _item(session, "sablier_fidelite", bonuses={"effect": "daily_guard"})
    pid = _player(session)
    PlayerRepository(session).set_daily_streak(pid, 10)
    InventoryRepository(session).add_item(pid, guard, 1)
    CooldownRepository(session).upsert(pid, "daily", last_used_at=NOW - timedelta(days=2),
                                       next_available_at=NOW - timedelta(days=1, hours=1))
    res = ClaimDailyRewardUseCase(PlayerRepository(session), CooldownRepository(session),
                                  CooldownService()).execute(1, "u", "U")
    assert res.success and res.guard_used and res.streak == 11       # pas 10 // 2 + 1
    assert _qty(session, pid, guard) == 0
    assert missed_after_guard(3, True) == (2, True) and missed_after_guard(0, True) == (0, False)


# ------------------------------------------------------------ cosmétiques --
def test_un_cosmetique_porte_n_est_affiche_que_s_il_est_possede(session):
    look = {"cosmetic": "cadre", "color": [255, 160, 200], "glow": True}
    frame = _item(session, "cadre_test", category="cosmetic", bonuses=look)
    pid = _player(session)
    PlayerCosmeticRepository(session).set(pid, "cadre", "cadre_test")
    assert worn_cosmetics(session, pid) == {}                         # pas (plus) possédé
    InventoryRepository(session).add_item(pid, frame, 1)
    assert worn_cosmetics(session, pid) == {"cadre": look}
