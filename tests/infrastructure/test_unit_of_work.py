"""Écritures atomiques (roadmap N8, 26/10/2026) : une opération en plusieurs
étapes est validée en entier, ou pas du tout — un plantage entre deux étapes
ne laisse plus d'or perdu ni d'objet dupliqué."""

import pytest
from sqlalchemy import select

from app.application.use_cases.buy_from_shop import BuyFromShopUseCase
from app.application.use_cases.transfer_gold import TransferGoldUseCase
from app.domain.services.shop_pricing_service import ShopPricingService
from app.infrastructure.db.models.player_cosmetic_model import PlayerCosmeticModel  # noqa: F401
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.shop_repository import ShopRepository
from app.infrastructure.db.unit_of_work import atomic, in_atomic
from tests.infrastructure.test_merchant_tools import _item, _player, _qty
from tests.infrastructure.test_use_consumable import session  # noqa: F401


def _gold(session, pid) -> int:
    session.expire_all()
    return session.execute(select(PlayerResourceModel.gold).where(PlayerResourceModel.player_id == pid)).scalar_one()


def test_atomic_valide_a_la_sortie_et_annule_sur_exception(session):
    pid = _player(session, gold=1000)
    players = PlayerRepository(session)
    with atomic(session):
        players.add_gold(pid, -100)
        assert in_atomic(session)
    assert _gold(session, pid) == 900
    with pytest.raises(RuntimeError):
        with atomic(session):
            players.add_gold(pid, -500)       # le dépôt ne valide pas lui-même…
            raise RuntimeError("panne")
    assert _gold(session, pid) == 900         # …donc rien n'est resté
    assert not in_atomic(session)


def test_les_blocs_s_imbriquent_seul_l_exterieur_valide(session):
    pid = _player(session, gold=1000)
    players = PlayerRepository(session)
    with pytest.raises(RuntimeError):
        with atomic(session):
            with atomic(session):
                players.add_gold(pid, -300)
            raise RuntimeError("panne après le bloc intérieur")
    assert _gold(session, pid) == 1000


def test_un_achat_qui_plante_ne_coute_rien(session, monkeypatch):
    potion = _item(session, "potion_test")
    ShopRepository(session).create(potion, buy_price=100, max_sell_price=0, min_sell_price=0, stock_threshold=100)
    pid = _player(session, gold=1000)

    def panne(*args, **kwargs):
        raise RuntimeError("le disque lâche")

    monkeypatch.setattr(InventoryRepository, "add_item", panne)
    use_case = BuyFromShopUseCase(PlayerRepository(session), InventoryRepository(session),
                                  ShopRepository(session), ShopPricingService())
    with pytest.raises(RuntimeError):
        use_case.execute(1, "u", "U", "potion_test", 1)
    assert _gold(session, pid) == 1000 and _qty(session, pid, potion) == 0


def test_un_virement_qui_plante_ne_perd_pas_d_or(session, monkeypatch):
    sender = _player(session, gold=1000)
    receiver = PlayerRepository(session).get_or_create_by_discord_id(2, "v", "V").player.id
    original = PlayerRepository.add_gold
    calls = []

    def add_gold_puis_panne(self, player_id, gold, commit=True):
        calls.append(player_id)
        if len(calls) == 2:
            raise RuntimeError("panne au crédit")
        return original(self, player_id, gold, commit)

    monkeypatch.setattr(PlayerRepository, "add_gold", add_gold_puis_panne)
    with pytest.raises(RuntimeError):
        TransferGoldUseCase(PlayerRepository(session)).execute(
            sender_discord_id=1, sender_username="u", sender_display_name="U",
            receiver_discord_id=2, receiver_display_name="V", amount=300)
    assert _gold(session, sender) == 1000 and _gold(session, receiver) == 0
