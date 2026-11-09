"""Cartes à collectionner de bout en bout (base en mémoire) : booster offert
puis payé, pitié, recyclage, fabrication, titres de l'album, effets, reset."""

import random
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases import cards
from app.domain.services import card_service as cs
from app.infrastructure.cards import card_loader
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.card_model import PlayerCardStateModel
from app.infrastructure.db.models.monitoring_model import GameEventModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.repositories.card_repository import CardRepository
from app.infrastructure.db.repositories.inventory_repository import InventoryRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.repositories.player_title_repository import PlayerTitleRepository
from app.infrastructure.db.seeders.seed_content import seed_card_items

NOW = datetime(2026, 11, 9, 20, 0, tzinfo=UTC)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    seed_card_items(s)
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _player(session, discord_id=1, gold=0) -> int:
    profile = PlayerRepository(session).get_or_create_by_discord_id(
        discord_id=discord_id, username=f"u{discord_id}", display_name=f"Joueur {discord_id}")
    session.query(PlayerResourceModel).filter_by(player_id=profile.player.id).update({"gold": gold})
    session.commit()
    return profile.player.id


def _gold(session, player_id) -> int:
    return PlayerRepository(session).get_profile_by_player_id(player_id).resources.gold


def _give(session, player_id, code, quantity=1, brillante=False):
    item_id = CardRepository(session).item_ids()[card_loader.item_code(code, brillante)]
    InventoryRepository(session).add_item(player_id, item_id, quantity)


def test_le_premier_booster_est_offert_puis_deux_mille_or(session):
    pid = _player(session, gold=5000)
    first = cards.open_boosters(session, pid, 1, rng=random.Random(1), now=NOW)
    assert first.ok and first.free and first.gold_spent == 0 and len(first.cards) == 5
    assert _gold(session, pid) == 5000
    normal, brillante = CardRepository(session).owned(pid)
    assert sum(normal.values()) + sum(brillante.values()) == 5
    second = cards.open_boosters(session, pid, 1, rng=random.Random(2), now=NOW)
    assert second.ok and not second.free and second.gold_spent == cs.BOOSTER_PRICE
    assert _gold(session, pid) == 5000 - cs.BOOSTER_PRICE
    # Or étiqueté « cartes » pour la surveillance ; un événement par ouverture.
    refs = [e.ref for e in session.query(GameEventModel).filter_by(kind="gold", player_id=pid)]
    assert refs == ["cartes"]
    assert session.query(GameEventModel).filter_by(kind="booster", player_id=pid).count() == 2


def test_plusieurs_boosters_d_un_coup_le_premier_offert_compris(session):
    pid = _player(session, gold=10_000)
    result = cards.open_boosters(session, pid, 3, rng=random.Random(3), now=NOW)
    assert result.ok and result.free and result.gold_spent == 2 * cs.BOOSTER_PRICE
    assert len(result.boosters) == 3 and len(result.cards) == 15
    state = session.get(PlayerCardStateModel, pid)
    assert state.boosters_opened == 3 and state.free_booster_used


def test_pas_assez_d_or_rien_ne_bouge(session):
    pid = _player(session, gold=0)
    cards.open_boosters(session, pid, 1, rng=random.Random(4), now=NOW)          # l'offert
    refused = cards.open_boosters(session, pid, 1, rng=random.Random(5), now=NOW)
    assert not refused.ok and "manque" in refused.message
    normal, brillante = CardRepository(session).owned(pid)
    assert sum(normal.values()) + sum(brillante.values()) == 5
    assert session.get(PlayerCardStateModel, pid).boosters_opened == 1


def test_la_pitie_tombe_et_le_legendaire_est_brillant(session):
    pid = _player(session, gold=100_000)
    cards.open_boosters(session, pid, 1, rng=random.Random(6), now=NOW)
    session.get(PlayerCardStateModel, pid).since_top = cs.PITY_BOOSTERS - 1
    session.commit()
    result = cards.open_boosters(session, pid, 1, rng=random.Random(7), now=NOW)
    top = [c for c in result.cards if c.card.rarity in cs.TOP_RARITIES]
    assert top and result.since_top == 0
    if any(c.pity for c in result.cards):
        assert all(c.brillante for c in result.cards if c.pity)


def test_recycler_garde_un_exemplaire_de_chaque_version(session):
    pid = _player(session)
    _give(session, pid, "slime", 4)
    _give(session, pid, "gobelin_assassin", 2, brillante=True)
    coll = cards.collection(session, pid)
    expected = 3 * cs.PETALS["common"] + cs.PETALS["rare"] * cs.BRILLANTE_PETAL_MULT
    assert coll.duplicates == 4 and coll.duplicate_petals == expected
    result = cards.recycle_duplicates(session, pid)
    assert (result.cards, result.petals, result.petals_total) == (4, expected, expected)
    normal, brillante = CardRepository(session).owned(pid)
    assert normal == {"slime": 1} and brillante == {"gobelin_assassin": 1}


def test_fabriquer_une_carte_manquante(session):
    pid = _player(session)
    refused = cards.craft_card(session, pid, "gobelin_assassin")
    assert not refused.ok and "pétales" in refused.message
    state = CardRepository(session).state(pid)
    state.petals = cs.craft_cost("rare") + 7
    session.commit()
    made = cards.craft_card(session, pid, "gobelin_assassin", now=NOW)
    assert made.ok and made.petals_left == 7
    assert CardRepository(session).owned(pid)[0] == {"gobelin_assassin": 1}
    again = cards.craft_card(session, pid, "gobelin_assassin")
    assert not again.ok and "déjà" in again.message
    mythic = cards.craft_card(session, pid, "grand_cerisier")
    assert not mythic.ok and "brillante" in mythic.message


def test_titres_de_l_album_et_de_l_album_tout_brillant(session):
    pid = _player(session)
    all_cards = card_loader.list_cards()
    for card in all_cards[:16]:                       # 16/61 = 26 %
        _give(session, pid, card.code)
    assert cards.refresh_titles(session, pid) == ["🎴 Collectionneur"]
    for card in all_cards:
        _give(session, pid, card.code, brillante=True)
    unlocked = cards.refresh_titles(session, pid)
    assert {"📚 Archiviste", "🗃️ Conservateur", "🌸 Maître de l'album", "✨ Prisme du Grand Cerisier"} == set(unlocked)
    titles = set(PlayerTitleRepository(session).list_codes_for_player(pid))
    assert {"album_25", "album_50", "album_75", "album_100", "album_brillant"} <= titles


def test_les_cartes_possedees_donnent_leurs_effets(session):
    pid = _player(session)
    assert cards.player_card_bonuses(session, pid) == cs.CardBonuses()
    _give(session, pid, "kairos")
    _give(session, pid, "slime", 3)
    _give(session, pid, "slime_titan", brillante=True)
    bonuses = cards.player_card_bonuses(session, pid)
    assert bonuses.xp_pct == 2
    assert bonuses.damage_vs_mob == {"slime": 3} and bonuses.drop_vs_mob == {"slime": 5}
    assert bonuses.boss_damage["slime_titan"] == 10


def test_la_carte_de_sylve_accelere_la_regeneration(session):
    from app.application.services.status_effect_resolver import resolve_regen_boosts

    pid = _player(session)
    assert resolve_regen_boosts(session, pid) == []
    _give(session, pid, "sylve")
    windows = resolve_regen_boosts(session, pid)
    assert len(windows) == 1 and windows[0][2] == 1.25


def test_la_carte_d_ysaline_baisse_ses_prix(session):
    from app.application.use_cases.reveal_element_talent import RevealElementTalentUseCase

    pid = _player(session)
    use_case = RevealElementTalentUseCase(session, (1000, 2000, 3000))
    assert use_case.status(pid).next_price == 1000
    _give(session, pid, "ysaline")
    assert use_case.status(pid).next_price == 950


def test_le_reset_du_joueur_efface_ses_cartes_et_son_etat(session):
    from app.application.use_cases.reset_player import ResetPlayerUseCase

    pid = _player(session, gold=10_000)
    cards.open_boosters(session, pid, 2, rng=random.Random(8), now=NOW)
    ResetPlayerUseCase().execute(session, pid)
    session.commit()
    assert CardRepository(session).owned(pid) == ({}, {})
    assert session.get(PlayerCardStateModel, pid) is None
    assert cards.collection(session, pid).free_booster


def test_le_record_de_l_album(session):
    from app.infrastructure.db.repositories.records_repository import RecordsRepository

    a, b = _player(session, 1), _player(session, 2)
    for code in ("slime", "gobelin", "zombie"):
        _give(session, a, code)
    _give(session, b, "slime", 5)
    entries = {e.player_id: e.value for e in RecordsRepository(session).album_entries()}
    assert entries == {a: 3, b: 1}
