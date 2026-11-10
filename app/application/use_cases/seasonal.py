"""Événements saisonniers : calendrier de l'Avent, cadeau de Noël, objets et
boutiques d'événement, Nouvel An (décembre 2026, demande de l'auteur).

Règles pures dans `seasonal_service`, contenu dans `seasonal_events.json`.
Chaque prise est ATOMIQUE : récompenses, monnaie et trace de la prise sont
validées ensemble, ou rien.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.services import seasonal_service as ss
from app.domain.services.little_girl_service import CHOICE_HELP, CHOICE_IGNORE
from app.domain.services.monitoring import kinds
from app.infrastructure.db.models.inventory_model import PlayerInventoryItemModel
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.seasonal_repository import SeasonalRepository
from app.infrastructure.db.unit_of_work import atomic
from app.infrastructure.monitoring.telemetry import record as record_event
from app.infrastructure.seasonal import seasonal_loader
from app.shared.formatters import format_int

_logger = logging.getLogger(__name__)

ADVENT = "advent"
CHRISTMAS = "christmas"
GIFT_KEY = "gift"


def content() -> ss.SeasonalContent:
    return seasonal_loader.get_content()


def _now(now: datetime | None) -> datetime:
    now = now or datetime.now(UTC)
    return now if now.tzinfo else now.replace(tzinfo=UTC)


# ------------------------------------------------------------- récompenses
@dataclass(frozen=True)
class Granted:
    """Une récompense reçue, prête à afficher."""
    emoji: str
    text: str


def item_names(session: Session, codes) -> dict[str, str]:
    repo = ItemRepository(session)
    names = {}
    for code in set(codes):
        item = repo.get_by_code(code)
        names[code] = item.name if item is not None else code
    return names


def reward_line(reward: ss.Reward, level: int, names: dict[str, str]) -> Granted:
    if reward.kind == ss.ITEM:
        return Granted("🎁", f"{reward.qty} × {names.get(reward.item, reward.item)}")
    return Granted("💰", f"{format_int(reward.gold(level))} or")


def grant(session: Session, player_id: int, level: int, rewards, source: str = "evenement") -> list[Granted]:
    """Donne les récompenses (dans la transaction de l'appelant)."""
    players, inventory, items = PlayerRepository(session), InventoryRepository(session), ItemRepository(session)
    given = []
    for reward in rewards:
        if reward.kind == ss.ITEM:
            item = items.get_by_code(reward.item)
            if item is None or reward.qty < 1:
                _logger.warning("récompense d'événement ignorée : objet %s introuvable", reward.item)
                continue
            inventory.add_item(player_id, item.id, reward.qty, commit=False)
            given.append(Granted("🎁", f"{reward.qty} × {item.name}"))
        else:
            gold = reward.gold(level)
            if gold > 0:
                players.add_gold(player_id, gold, commit=False, source=source)
                given.append(Granted("💰", f"{format_int(gold)} or"))
    return given


def item_quantity(session: Session, player_id: int, item_code: str) -> int:
    item = ItemRepository(session).get_by_code(item_code)
    if item is None:
        return 0
    qty = session.execute(
        select(PlayerInventoryItemModel.quantity).where(
            PlayerInventoryItemModel.player_id == player_id,
            PlayerInventoryItemModel.item_definition_id == item.id)
    ).scalar_one_or_none()
    return int(qty or 0)


def _level(session: Session, player_id: int) -> int:
    profile = PlayerRepository(session).get_profile_by_player_id(player_id)
    return profile.progression.level if profile is not None else 1


# --------------------------------------------------------------- l'Avent
@dataclass(frozen=True)
class AdventStatus:
    advent: ss.Advent
    today_day: int | None          # la case du jour (None hors du calendrier)
    opened: frozenset[int]
    states: tuple[str, ...]
    level: int
    names: dict[str, str]

    @property
    def can_open(self) -> bool:
        return self.today_day is not None and self.today_day not in self.opened

    def lines(self, day: int) -> list[Granted]:
        return [reward_line(r, self.level, self.names) for r in self.advent.rewards(day)]


def _door_key(advent: ss.Advent, day: int) -> str:
    return (advent.start + timedelta(days=day - 1)).isoformat()


def advent_status(session: Session, player_id: int, now: datetime | None = None) -> AdventStatus | None:
    advent = content().advent
    if advent is None or not advent.enabled or not advent.size:
        return None
    now = _now(now)
    today = ss.paris_day(now)
    keys = SeasonalRepository(session).claim_keys(player_id, ADVENT)
    opened = frozenset(n for n in range(1, advent.size + 1) if _door_key(advent, n) in keys)
    names = item_names(session, [r.item for day in advent.days for r in day if r.kind == ss.ITEM])
    return AdventStatus(advent, advent.day_of(today), opened, tuple(ss.door_states(advent, today, set(opened))),
                        _level(session, player_id), names)


@dataclass(frozen=True)
class ClaimResult:
    ok: bool
    message: str
    granted: list[Granted] = field(default_factory=list)
    day: int | None = None
    kindness: ss.Kindness | None = None


def open_advent_door(session: Session, player_id: int, now: datetime | None = None) -> ClaimResult:
    """Ouvre la case du jour : on n'ouvre QUE celle du jour."""
    now = _now(now)
    advent = content().advent
    if advent is None or not advent.enabled:
        return ClaimResult(False, "🎄 Pas de calendrier de l'Avent en ce moment.")
    day = advent.day_of(ss.paris_day(now))
    if day is None:
        return ClaimResult(False, f"🎄 Le calendrier ouvre le {advent.start.strftime('%d/%m')} "
                                  f"et se referme le {advent.end.strftime('%d/%m')}.")
    repo = SeasonalRepository(session)
    key = _door_key(advent, day)
    try:
        with atomic(session):
            if repo.has_claimed(player_id, ADVENT, key):
                return ClaimResult(False, f"✅ Tu as déjà ouvert la case **{day}** — reviens demain !", day=day)
            level = _level(session, player_id)
            granted = grant(session, player_id, level, advent.rewards(day))
            repo.add_claim(player_id, ADVENT, key, {"day": day}, now)
            record_event(session, kinds.SEASONAL, player_id=player_id, ref=f"advent:{day}",
                         gold=sum(r.gold(level) for r in advent.rewards(day)))
    except IntegrityError:      # deux clics en même temps : un seul passe
        session.rollback()
        return ClaimResult(False, f"✅ Tu as déjà ouvert la case **{day}** — reviens demain !", day=day)
    return ClaimResult(True, f"🎄 Case **{day}** ouverte !", granted, day)


# ------------------------------------------------------------------ Noël
def kindness_of(session: Session, player_id: int, christmas: ss.Christmas | None = None) -> ss.Kindness:
    """La gentillesse du joueur : ses choix face à la petite fille, apparue
    AVANT le jour du cadeau (le réveillon fige le compte)."""
    christmas = christmas or content().christmas
    rules = christmas.kindness if christmas is not None else ss.KindnessRules()
    until = ss.day_start(christmas.gift_day) if christmas is not None else datetime.now(UTC)
    choices = SeasonalRepository(session).little_girl_choices(player_id, until)
    return ss.kindness(choices.get(CHOICE_HELP, 0), choices.get(CHOICE_IGNORE, 0), rules)


@dataclass(frozen=True)
class ChristmasStatus:
    christmas: ss.Christmas
    open: bool
    claimed: bool
    kindness: ss.Kindness
    gift: tuple[ss.Reward, ...]      # le cadeau À SA gentillesse
    level: int
    names: dict[str, str]

    @property
    def lines(self) -> list[Granted]:
        return [reward_line(r, self.level, self.names) for r in self.gift]


def christmas_status(session: Session, player_id: int, now: datetime | None = None) -> ChristmasStatus | None:
    christmas = content().christmas
    if christmas is None or not christmas.enabled:
        return None
    k = kindness_of(session, player_id, christmas)
    gift = christmas.gift_for(k)
    return ChristmasStatus(
        christmas, christmas.gift_open(ss.paris_day(_now(now))),
        SeasonalRepository(session).has_claimed(player_id, CHRISTMAS, GIFT_KEY), k, gift,
        _level(session, player_id), item_names(session, [r.item for r in christmas.rewards if r.kind == ss.ITEM]))


def open_christmas_gift(session: Session, player_id: int, now: datetime | None = None) -> ClaimResult:
    now = _now(now)
    christmas = content().christmas
    if christmas is None or not christmas.enabled:
        return ClaimResult(False, "🎅 Pas de cadeau de Noël en ce moment.")
    today = ss.paris_day(now)
    if today < christmas.gift_day:
        return ClaimResult(False, f"🎅 Patience : le Père Noël passe dans la nuit du "
                                  f"{(christmas.gift_day - timedelta(days=1)).strftime('%d/%m')}.")
    if today > christmas.claim_until:
        return ClaimResult(False, "🎅 Le Père Noël est reparti : les cadeaux se prenaient jusqu'au "
                                  f"{christmas.claim_until.strftime('%d/%m')}.")
    repo = SeasonalRepository(session)
    k = kindness_of(session, player_id, christmas)
    try:
        with atomic(session):
            if repo.has_claimed(player_id, CHRISTMAS, GIFT_KEY):
                return ClaimResult(False, "🎁 Tu as déjà ouvert ton cadeau !", kindness=k)
            level = _level(session, player_id)
            gift = christmas.gift_for(k)
            granted = grant(session, player_id, level, gift)
            repo.add_claim(player_id, CHRISTMAS, GIFT_KEY, {"tier": k.tier, "pct": k.pct,
                                                            "helps": k.helps, "ignores": k.ignores}, now)
            record_event(session, kinds.SEASONAL, player_id=player_id, ref="christmas", qty=k.pct,
                         gold=sum(r.gold(level) for r in gift), data={"tier": k.tier})
    except IntegrityError:
        session.rollback()
        return ClaimResult(False, "🎁 Tu as déjà ouvert ton cadeau !", kindness=k)
    return ClaimResult(True, "🎁 Cadeau ouvert !", granted, kindness=k)


# ------------------------------------------------- objets d'événement
def event_drops(now: datetime | None = None) -> list[tuple[str, int]]:
    """(objet, quantité par monstre) des objets d'événement en cours —
    donnés à chaque survivant pour chaque monstre de zone vaincu."""
    return [(d.item, d.per_kill) for d in ss.active_drops(content().drops, ss.paris_day(_now(now)))]


# --------------------------------------------- boutiques d'événement
@dataclass(frozen=True)
class ShopStatus:
    shop: ss.EventShop
    open: bool
    balance: int                     # monnaie du joueur
    bought: dict[str, int]
    names: dict[str, str]

    @property
    def currency_name(self) -> str:
        return self.names.get(self.shop.currency, self.shop.currency)

    def left(self, offer: ss.ShopOffer) -> int:
        return ss.max_buyable(offer, self.balance, self.bought.get(offer.item, 0))


def shop_status(session: Session, player_id: int, shop_code: str, now: datetime | None = None) -> ShopStatus | None:
    shop = content().shop(shop_code)
    if shop is None:
        return None
    names = item_names(session, [shop.currency, *(o.item for o in shop.offers)])
    return ShopStatus(shop, shop.is_open(ss.paris_day(_now(now))), item_quantity(session, player_id, shop.currency),
                      SeasonalRepository(session).purchases(player_id, shop.code), names)


@dataclass(frozen=True)
class PurchaseResult:
    ok: bool
    message: str
    balance: int = 0


def buy(session: Session, player_id: int, shop_code: str, item_code: str, quantity: int = 1,
        now: datetime | None = None) -> PurchaseResult:
    """Achète `quantity` × `item_code` avec la monnaie de la boutique."""
    now = _now(now)
    shop = content().shop(shop_code)
    if shop is None:
        return PurchaseResult(False, "❌ Boutique inconnue.")
    if not shop.is_open(ss.paris_day(now)):
        return PurchaseResult(False, f"{shop.emoji} {shop.name} est fermé(e) : ouvert du "
                                     f"{shop.opens.strftime('%d/%m')} au {shop.closes.strftime('%d/%m')}.")
    offer = shop.offer(item_code)
    if offer is None:
        return PurchaseResult(False, "❌ Cet article n'est pas (ou plus) en vente.")
    quantity = int(quantity)
    if quantity < 1:
        return PurchaseResult(False, "❌ Quantité invalide.")
    items, inventory, repo = ItemRepository(session), InventoryRepository(session), SeasonalRepository(session)
    with atomic(session):
        currency, item = items.get_by_code(shop.currency), items.get_by_code(offer.item)
        if currency is None or item is None:
            return PurchaseResult(False, "❌ Article indisponible (contenu à installer).")
        balance = item_quantity(session, player_id, shop.currency)
        bought = repo.purchases(player_id, shop.code).get(offer.item, 0)
        if offer.limit and bought + quantity > offer.limit:
            left = max(0, offer.limit - bought)
            return PurchaseResult(False, f"❌ Limite atteinte : {offer.limit} par joueur "
                                         f"({'plus aucun' if not left else f'encore {left}'} pour toi).", balance)
        cost = offer.price * quantity
        if balance < cost:
            return PurchaseResult(False, f"❌ Il te manque **{format_int(cost - balance)}** × {currency.name} "
                                         f"({format_int(cost)} pour {quantity}).", balance)
        inventory.remove_item(player_id, currency.id, cost, commit=False)
        inventory.add_item(player_id, item.id, quantity, commit=False)
        repo.add_purchase(player_id, shop.code, offer.item, quantity)
        record_event(session, kinds.SEASONAL, player_id=player_id, ref=f"shop:{shop.code}:{offer.item}",
                     qty=quantity, data={"cost": cost, "currency": shop.currency})
    return PurchaseResult(True, f"{shop.emoji} **{quantity} × {item.name}** pour {format_int(cost)} × "
                                f"{currency.name} — il t'en reste {format_int(balance - cost)}.", balance - cost)


# ---------------------------------------------------------------- Nouvel An
def new_year_active(now: datetime | None = None) -> bool:
    n = content().new_year
    return n is not None and n.active(_now(now))


def new_year_window() -> tuple[datetime, datetime] | None:
    n = content().new_year
    return n.window() if n is not None and n.enabled else None
