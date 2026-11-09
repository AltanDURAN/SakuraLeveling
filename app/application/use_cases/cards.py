"""Cartes à collectionner : ouvrir des boosters, recycler les doublons,
fabriquer une carte manquante, et ce que rapportent les cartes possédées.

Règles pures : `app/domain/services/card_service.py`. Les cartes sont des
objets d'inventaire (catégorie `carte`) ; l'état du joueur (pétales, pitié,
booster offert) est dans `player_card_states`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.application.services.title_unlock_service import TitleUnlockService
from app.domain.services import card_service as cs
from app.domain.services.monitoring import kinds
from app.infrastructure.cards import card_loader
from app.infrastructure.db.repositories.card_repository import CardRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_kill_repository import PlayerKillRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_title_repository import PlayerTitleRepository
from app.infrastructure.db.unit_of_work import atomic
from app.infrastructure.monitoring.telemetry import record as record_event

#: Au plus, d'un coup (un message de résultat doit rester lisible).
MAX_BOOSTERS = 10
NOT_INSTALLED = "🃏 Les cartes ne sont pas encore installées sur ce serveur (contenu à charger)."


# ------------------------------------------------------------ collection --
@dataclass(frozen=True)
class Collection:
    cards: list[cs.CardDef]
    normal: dict[str, int]
    brillante: dict[str, int]
    album: cs.Album
    petals: int
    boosters_opened: int
    since_top: int
    free_booster: bool          # le booster offert est encore à prendre

    def owns(self, code: str) -> bool:
        return self.normal.get(code, 0) > 0 or self.brillante.get(code, 0) > 0

    @property
    def duplicates(self) -> int:
        return sum(cs.duplicates(q) for q in [*self.normal.values(), *self.brillante.values()])

    @property
    def duplicate_petals(self) -> int:
        """Ce que rapporterait le recyclage de tous les doublons."""
        rarity = {c.code: c.rarity for c in self.cards}
        total = 0
        for owned, shiny in ((self.normal, False), (self.brillante, True)):
            for code, quantity in owned.items():
                total += cs.duplicates(quantity) * cs.petals_for(rarity.get(code, "common"), shiny)
        return total


def collection(session: Session, player_id: int) -> Collection:
    repo = CardRepository(session)
    normal, brillante = repo.owned(player_id)
    state = repo.find_state(player_id)
    cards = card_loader.list_cards()
    return Collection(
        cards=cards, normal=normal, brillante=brillante,
        album=cs.album(cards, normal, brillante),
        petals=state.petals if state else 0,
        boosters_opened=state.boosters_opened if state else 0,
        since_top=state.since_top if state else 0,
        free_booster=not (state and state.free_booster_used),
    )


def owned_cards(session: Session, player_id: int) -> list[cs.CardDef]:
    """Les cartes possédées (normale ou brillante), une fois chacune."""
    normal, brillante = CardRepository(session).owned(player_id)
    return [c for c in card_loader.list_cards() if normal.get(c.code) or brillante.get(c.code)]


def player_card_bonuses(session: Session, player_id: int) -> cs.CardBonuses:
    """Ce que rapportent les cartes du joueur. Ne lève jamais : une panne
    des cartes ne doit pas bloquer un combat."""
    try:
        return cs.card_bonuses(owned_cards(session, player_id))
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("bonus des cartes illisibles pour %s", player_id, exc_info=True)
        return cs.CardBonuses()


def _check_titles(session: Session, player_id: int, album: cs.Album) -> list[str]:
    events = TitleUnlockService(PlayerTitleRepository(session), PlayerKillRepository(session)).check_card_album(
        player_id, album.percent, album.brillante_complete)
    return [f"{e.title.icon} {e.title.name}" for e in events]


def _album_grew(state, before: cs.Album, after: cs.Album, now: datetime) -> None:
    if after.owned > before.owned:
        state.album_count = after.owned
        state.album_at = now.replace(tzinfo=None)


# ---------------------------------------------------------------- booster --
@dataclass(frozen=True)
class OpenedCard:
    card: cs.CardDef
    brillante: bool
    new: bool                   # la carte entre dans l'album
    new_brillante: bool         # sa première brillante
    pity: bool = False


@dataclass(frozen=True)
class BoosterResult:
    ok: bool
    message: str = ""
    boosters: list[list[OpenedCard]] = field(default_factory=list)
    gold_spent: int = 0
    free: bool = False
    gold_left: int = 0
    album_before: cs.Album | None = None
    album_after: cs.Album | None = None
    since_top: int = 0
    titles: list[str] = field(default_factory=list)

    @property
    def cards(self) -> list[OpenedCard]:
        return [c for booster in self.boosters for c in booster]

    @property
    def best(self) -> OpenedCard | None:
        return max(self.cards, key=lambda c: (cs.rarity_index(c.card.rarity), c.brillante), default=None)


def booster_price(count: int, free_available: bool) -> int:
    return cs.BOOSTER_PRICE * max(0, count - (1 if free_available else 0))


def open_boosters(session: Session, player_id: int, count: int = 1, *,
                  rng: random.Random | None = None, now: datetime | None = None) -> BoosterResult:
    """Achète et ouvre `count` boosters (le premier de la saison est offert).
    Tout ou rien : or, cartes, pitié et titres sont validés ensemble."""
    count = max(1, min(MAX_BOOSTERS, int(count)))
    rng = rng or random.SystemRandom()
    now = now or datetime.now(UTC)
    players = PlayerRepository(session)
    repo = CardRepository(session)
    with atomic(session):
        profile = players.get_profile_by_player_id(player_id)
        if profile is None:
            return BoosterResult(False, "❌ Profil introuvable.")
        item_ids = repo.item_ids()
        cards = card_loader.list_cards()
        if not cards or not item_ids:
            return BoosterResult(False, NOT_INSTALLED)
        state = repo.state(player_id)
        free = not state.free_booster_used
        price = booster_price(count, free)
        gold = profile.resources.gold
        if gold < price:
            missing = price - gold
            return BoosterResult(False, f"❌ Il te manque **{missing:,}** or pour {count} booster"
                                        f"{'s' if count > 1 else ''} ({price:,} or).".replace(",", " "),
                                 gold_left=gold)
        if price:
            players.add_gold(player_id, -price, source="cartes")
        normal, brillante = repo.owned(player_id)
        before = cs.album(cards, normal, brillante)
        bonus = cs.card_bonuses([c for c in cards if normal.get(c.code) or brillante.get(c.code)])
        pool = card_loader.by_rarity()
        by_code = {c.code: c for c in cards}
        inventory = InventoryRepository(session)
        opened: list[list[OpenedCard]] = []
        for _ in range(count):
            pulls, state.since_top = cs.open_booster(
                pool, rng, state.since_top, cs.BRILLANTE_PCT + bonus.brillante_bonus_pct)
            booster = []
            for pull in pulls:
                card = by_code[pull.code]
                code = card_loader.item_code(card.code, pull.brillante)
                if code not in item_ids:
                    raise RuntimeError(f"carte absente de la base : {code} (relancer seed_content)")
                new = not (normal.get(card.code) or brillante.get(card.code))
                new_shiny = pull.brillante and not brillante.get(card.code)
                inventory.add_item(player_id, item_ids[code], 1, commit=False)
                target = brillante if pull.brillante else normal
                target[card.code] = target.get(card.code, 0) + 1
                booster.append(OpenedCard(card, pull.brillante, new, new_shiny, pull.pity))
            opened.append(booster)
        after = cs.album(cards, normal, brillante)
        state.boosters_opened += count
        state.free_booster_used = True
        state.updated_at = now.replace(tzinfo=None)
        _album_grew(state, before, after, now)
        titles = _check_titles(session, player_id, after)
        result = BoosterResult(True, boosters=opened, gold_spent=price, free=free, gold_left=gold - price,
                               album_before=before, album_after=after, since_top=state.since_top, titles=titles)
        best = result.best
        record_event(session, kinds.BOOSTER, player_id=player_id, qty=count, gold=-price,
                     ref=best.card.code if best else None,
                     data={"best": best.card.rarity if best else "", "free": free,
                           "new": sum(c.new for c in result.cards),
                           "brillantes": sum(c.brillante for c in result.cards)})
        return result


# ------------------------------------------------------------- recyclage --
@dataclass(frozen=True)
class RecycleResult:
    cards: int
    petals: int
    petals_total: int


def recycle_duplicates(session: Session, player_id: int) -> RecycleResult:
    """Recycle tous les doublons en pétales (on garde un exemplaire de
    chaque version). Tout ou rien."""
    repo = CardRepository(session)
    with atomic(session):
        normal, brillante = repo.owned(player_id)
        item_ids = repo.item_ids()
        rarity = {c.code: c.rarity for c in card_loader.list_cards()}
        inventory = InventoryRepository(session)
        cards = petals = 0
        for owned, shiny in ((normal, False), (brillante, True)):
            for code, quantity in owned.items():
                extra = cs.duplicates(quantity)
                item_id = item_ids.get(card_loader.item_code(code, shiny))
                if not extra or item_id is None or code not in rarity:
                    continue
                if inventory.remove_item(player_id, item_id, extra, commit=False):
                    cards += extra
                    petals += extra * cs.petals_for(rarity[code], shiny)
        state = repo.state(player_id)
        state.petals += petals
        if cards:
            record_event(session, kinds.CARD_RECYCLE, player_id=player_id, qty=cards, data={"petals": petals})
        return RecycleResult(cards, petals, state.petals)


# ------------------------------------------------------------ fabrication --
@dataclass(frozen=True)
class CraftResult:
    ok: bool
    message: str
    card: cs.CardDef | None = None
    petals_left: int = 0
    titles: list[str] = field(default_factory=list)


def craft_card(session: Session, player_id: int, code: str, now: datetime | None = None) -> CraftResult:
    """Fabrique une carte MANQUANTE avec des pétales (jamais une brillante,
    donc jamais la mythique)."""
    now = now or datetime.now(UTC)
    card = card_loader.get_card(code)
    if card is None:
        return CraftResult(False, "❌ Carte inconnue.")
    if not cs.craftable(card):
        return CraftResult(False, f"❌ {card.name} ne se fabrique pas : elle n'existe qu'en brillante, "
                                  "il faut la tirer ou l'échanger.")
    repo = CardRepository(session)
    with atomic(session):
        normal, brillante = repo.owned(player_id)
        if normal.get(code) or brillante.get(code):
            return CraftResult(False, f"❌ Tu as déjà {card.name}.")
        state = repo.state(player_id)
        cost = cs.craft_cost(card.rarity)
        if state.petals < cost:
            return CraftResult(False, f"❌ Il te faut {cost:,} pétales (tu en as {state.petals:,}).".replace(",", " "),
                               petals_left=state.petals)
        item_id = repo.item_ids().get(card_loader.item_code(code))
        if item_id is None:
            return CraftResult(False, NOT_INSTALLED)
        cards = card_loader.list_cards()
        before = cs.album(cards, normal, brillante)
        state.petals -= cost
        InventoryRepository(session).add_item(player_id, item_id, 1, commit=False)
        normal[code] = 1
        after = cs.album(cards, normal, brillante)
        _album_grew(state, before, after, now)
        titles = _check_titles(session, player_id, after)
        record_event(session, kinds.CARD_CRAFT, player_id=player_id, ref=code, data={"petals": cost})
        return CraftResult(True, f"🌸 {card.name} rejoint ton album ({cost:,} pétales).".replace(",", " "),
                           card, state.petals, titles)


def refresh_titles(session: Session, player_id: int) -> list[str]:
    """Titres de l'album d'après ce que le joueur possède MAINTENANT (une
    carte reçue par échange ou à la brocante) — appelé à l'ouverture de
    l'album."""
    with atomic(session):
        cards = card_loader.list_cards()
        normal, brillante = CardRepository(session).owned(player_id)
        return _check_titles(session, player_id, cs.album(cards, normal, brillante))
