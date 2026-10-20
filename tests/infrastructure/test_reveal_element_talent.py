"""Papier élémentaire : révélation d'un talent, prix croissant, 1er offert."""

from datetime import datetime, UTC

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.use_cases.reveal_element_talent import RevealElementTalentUseCase
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.element_affinity_model import (  # noqa: F401
    PlayerElementAffinityModel,
)
from app.infrastructure.db.models.element_essence_model import (  # noqa: F401
    PlayerElementEssenceModel,
)
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel

PRICES = (0, 100, 300, 600, 1000, 2000, 3000, 5000)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            PlayerModel.__table__,
            PlayerProgressionModel.__table__,
            PlayerResourceModel.__table__,
            PlayerElementAffinityModel.__table__,
            PlayerElementEssenceModel.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    now = datetime.now(UTC)
    player = PlayerModel(id=1, discord_id=1, username="u", display_name="U",
                         created_at=now, updated_at=now, last_seen_at=now)
    player.progression = PlayerProgressionModel(level=1, xp=0, skill_points=0,
                                                created_at=now, updated_at=now)
    player.resources = PlayerResourceModel(gold=150, created_at=now, updated_at=now)
    s.add(player)
    s.commit()
    yield s
    s.close()


def _gold(session):
    return session.get(PlayerResourceModel, 1).gold


def test_premier_papier_offert_puis_prix_croissant(session):
    uc = RevealElementTalentUseCase(session, PRICES)
    assert uc.status(1).next_price == 0
    first = uc.execute(1, "feu")
    assert first.success and first.price == 0 and first.talent is not None
    assert _gold(session) == 150

    assert uc.status(1).next_price == 100
    second = uc.execute(1, "eau")
    assert second.success and second.price == 100
    assert _gold(session) == 50
    assert set(uc.status(1).revealed) == {"feu", "eau"}


def test_refus_si_deja_connu_ou_pas_assez_d_or(session):
    uc = RevealElementTalentUseCase(session, PRICES)
    uc.execute(1, "feu")
    again = uc.execute(1, "feu")
    assert not again.success and _gold(session) == 150

    uc.execute(1, "eau")  # 100 or → reste 50
    broke = uc.execute(1, "vent")  # coûte 300
    assert not broke.success
    assert "vent" in uc.status(1).unrevealed
    assert _gold(session) == 50


def test_tous_connus(session):
    session.get(PlayerResourceModel, 1).gold = 10**6
    session.commit()
    uc = RevealElementTalentUseCase(session, PRICES)
    for code in list(uc.status(1).unrevealed):
        assert uc.execute(1, code).success
    st = uc.status(1)
    assert st.next_price is None and not st.unrevealed and len(st.revealed) == 8
    assert _gold(session) == 10**6 - sum(PRICES)
