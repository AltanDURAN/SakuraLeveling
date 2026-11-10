"""Événements saisonniers de bout en bout (base en mémoire) : une case de
l'Avent par jour, le cadeau de Noël selon la gentillesse, l'atelier des
lutins (monnaie, limite, dates), les boosters offerts chez Sorn, le Nouvel An
(toutes les divinités) et la remise à zéro d'un joueur."""

import json
import random
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases import cards, seasonal
from app.application.use_cases.offering import active_blessings
from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.domain.services import seasonal_service as ss
from app.domain.services.offering_service import blessings_value
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.event_model import ActiveEventModel, EventParticipationModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.item_repository import ItemRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.seasonal_repository import SeasonalRepository
from app.infrastructure.db.seeders.seed_content import seed_card_items
from app.infrastructure.offering import offering_loader
from app.infrastructure.seasonal import seasonal_loader
from tests.domain.test_seasonal_service import RAW

ITEMS = json.loads((seasonal_loader.CONTENT_PATH.parent / "items.json").read_text(encoding="utf-8"))


def _paris(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=ss.PARIS)


@pytest.fixture()
def session(tmp_path, monkeypatch):
    path = tmp_path / "seasonal_events.json"
    path.write_text(json.dumps(RAW), encoding="utf-8")
    monkeypatch.setattr(seasonal_loader, "CONTENT_PATH", path)
    seasonal_loader.clear_cache()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    repo = ItemRepository(s)
    for it in ITEMS:
        repo.create(code=it["code"], name=it["name"], description=it["description"], category=it["category"],
                    rarity=it["rarity"], stackable=it["stackable"], max_stack=it["max_stack"],
                    sell_price=it["sell_price"], buy_price=it["buy_price"], icon=it["icon"],
                    stat_bonuses=it["stat_bonuses"], equipment_slot=it.get("equipment_slot"),
                    requires_two_hands=bool(it.get("requires_two_hands")), family=it.get("family", ""),
                    level_requirement=1, passive=it.get("passive", "") or "")
    seed_card_items(s)
    s.commit()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()
        seasonal_loader.clear_cache()


def _player(session, discord_id=1, gold=0, level=1) -> int:
    repo = PlayerRepository(session)
    pid = repo.get_or_create_by_discord_id(discord_id, f"u{discord_id}", f"Joueur {discord_id}").player.id
    if level > 1:
        repo.apply_progression(pid, level, 0, level - 1)
    session.query(PlayerResourceModel).filter_by(player_id=pid).update({"gold": gold})
    session.commit()
    return pid


def _gold(session, pid) -> int:
    return PlayerRepository(session).get_profile_by_player_id(pid).resources.gold


def _qty(session, pid, code) -> int:
    return seasonal.item_quantity(session, pid, code)


def _give(session, pid, code, qty):
    InventoryRepository(session).add_item(pid, ItemRepository(session).get_by_code(code).id, qty)


def test_une_case_de_l_avent_par_jour_le_jour_meme(session):
    pid = _player(session, level=7)
    early = seasonal.open_advent_door(session, pid, _paris(2026, 11, 30))
    assert not early.ok and "01/12" in early.message
    first = seasonal.open_advent_door(session, pid, _paris(2026, 12, 5))
    assert first.ok and first.day == 5 and _gold(session, pid) == 70          # 10 × niveau 7
    again = seasonal.open_advent_door(session, pid, _paris(2026, 12, 5, 23))
    assert not again.ok and "déjà" in again.message and _gold(session, pid) == 70
    last = seasonal.open_advent_door(session, pid, _paris(2026, 12, 24))
    assert last.ok and _qty(session, pid, "potion_soin") == 3 and _gold(session, pid) == 570
    status = seasonal.advent_status(session, pid, _paris(2026, 12, 24))
    assert status.opened == {5, 24} and not status.can_open
    assert status.states[3] == ss.MISSED and status.states[4] == ss.OPENED


def _little_girl(session, pid, choice, when):
    ev = ActiveEventModel(event_type="little_girl", channel_id=1, status="resolved", payload_json="{}",
                          created_at=when.astimezone(UTC).replace(tzinfo=None))
    session.add(ev)
    session.flush()
    session.add(EventParticipationModel(event_id=ev.id, player_id=pid, choice=choice, payload_json="{}"))
    session.commit()


def test_le_cadeau_de_noel_suit_la_gentillesse(session):
    players = {name: _player(session, discord_id=i, level=10) for i, name in
               enumerate(("ange", "sage", "vilain", "inconnu"), start=1)}
    for choice in ("aider", "aider"):
        _little_girl(session, players["ange"], choice, _paris(2026, 12, 10))
    for choice in ("aider", "ignorer"):
        _little_girl(session, players["sage"], choice, _paris(2026, 12, 11))
    for choice in ("aider", "ignorer", "ignorer"):
        _little_girl(session, players["vilain"], choice, _paris(2026, 12, 12))
    # Après le réveillon, ça ne compte plus.
    _little_girl(session, players["vilain"], "aider", _paris(2026, 12, 26))
    _little_girl(session, players["vilain"], "aider", _paris(2026, 12, 27))

    assert not seasonal.open_christmas_gift(session, players["ange"], _paris(2026, 12, 24)).ok
    golds = {}
    for name, pid in players.items():
        result = seasonal.open_christmas_gift(session, pid, _paris(2026, 12, 28))
        assert result.ok, name
        golds[name] = (_gold(session, pid), _qty(session, pid, "booster_offert"), result.kindness.tier)
    assert golds == {"ange": (1500, 5, ss.ANGEL), "sage": (1000, 3, ss.NICE),
                     "vilain": (500, 2, ss.NAUGHTY), "inconnu": (1000, 3, ss.UNKNOWN)}
    again = seasonal.open_christmas_gift(session, players["ange"], _paris(2026, 12, 29))
    assert not again.ok and _gold(session, players["ange"]) == 1500
    late_pid = _player(session, discord_id=9)
    assert not seasonal.open_christmas_gift(session, late_pid, _paris(2027, 1, 1)).ok


def test_l_atelier_des_lutins(session):
    pid = _player(session)
    _give(session, pid, "sucre_d_orge", 90)
    closed = seasonal.buy(session, pid, "lutins", "cadre_houx", 1, _paris(2026, 12, 24))
    assert not closed.ok and "fermé" in closed.message
    ok = seasonal.buy(session, pid, "lutins", "cadre_houx", 1, _paris(2026, 12, 25))
    assert ok.ok and _qty(session, pid, "cadre_houx") == 1 and _qty(session, pid, "sucre_d_orge") == 10
    limit = seasonal.buy(session, pid, "lutins", "cadre_houx", 1, _paris(2026, 12, 26))
    assert not limit.ok and "Limite" in limit.message
    poor = seasonal.buy(session, pid, "lutins", "potion_soin", 3, _paris(2026, 12, 26))
    assert not poor.ok and _qty(session, pid, "sucre_d_orge") == 10       # 12 demandés, rien n'a bougé
    potions = seasonal.buy(session, pid, "lutins", "potion_soin", 2, _paris(2026, 12, 31))
    assert potions.ok and _qty(session, pid, "potion_soin") == 2 and _qty(session, pid, "sucre_d_orge") == 2
    assert not seasonal.buy(session, pid, "lutins", "inconnu", 1, _paris(2026, 12, 31)).ok
    status = seasonal.shop_status(session, pid, "lutins", _paris(2026, 12, 31))
    assert status.bought == {"cadre_houx": 1, "potion_soin": 2} and status.balance == 2


def test_les_sucres_d_orge_tombent_seulement_pendant_la_semaine(session):
    assert seasonal.event_drops(_paris(2026, 12, 17, 23)) == []
    assert seasonal.event_drops(_paris(2026, 12, 18, 0)) == [("sucre_d_orge", 1)]
    assert seasonal.event_drops(_paris(2026, 12, 24, 23)) == [("sucre_d_orge", 1)]
    assert seasonal.event_drops(_paris(2026, 12, 25, 0)) == []


def test_les_boosters_offerts_passent_avant_l_or(session):
    pid = _player(session, gold=2000)
    _give(session, pid, "booster_offert", 2)
    first = cards.open_boosters(session, pid, 3, rng=random.Random(3))
    assert first.ok and first.free and first.gifts == 2 and first.gold_spent == 0
    assert _qty(session, pid, "booster_offert") == 0 and _gold(session, pid) == 2000
    paid = cards.open_boosters(session, pid, 1, rng=random.Random(4))
    assert paid.ok and paid.gifts == 0 and paid.gold_spent == 2000
    assert cards.collection(session, pid).gift_boosters == 0


def test_le_nouvel_an_reunit_toutes_les_divinites(session):
    assert active_blessings(session, _paris(2026, 12, 31, 23)) == []
    allofthem = active_blessings(session, _paris(2027, 1, 1, 10))
    assert {d.code for d in allofthem} == {d.code for d in offering_loader.list_deities()}
    assert blessings_value(allofthem, "xp_pct") == 10 and blessings_value(allofthem, "tower_tickets") == 1
    assert active_blessings(session, _paris(2027, 1, 2, 0)) == []


def test_le_reset_d_un_joueur_efface_ses_prises_et_achats(session):
    pid = _player(session)
    assert seasonal.open_advent_door(session, pid, _paris(2026, 12, 2)).ok
    _give(session, pid, "sucre_d_orge", 10)
    assert seasonal.buy(session, pid, "lutins", "potion_soin", 1, _paris(2026, 12, 25)).ok
    ResetPlayerUseCase().execute(session, pid)
    session.commit()
    repo = SeasonalRepository(session)
    assert repo.claim_keys(pid, seasonal.ADVENT) == set() and repo.purchases(pid, "lutins") == {}
