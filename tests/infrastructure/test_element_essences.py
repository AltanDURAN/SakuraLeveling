"""Intégration : drop d'essences → auto-conversion en affinité (repos réels)."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.services.encounter_service import EncounterService
from app.domain.services.element_affinity_progression_service import (
    ElementAffinityProgressionService,
)
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.element_affinity_model import (  # noqa: F401
    PlayerElementAffinityModel,
)
from app.infrastructure.db.models.element_essence_model import (  # noqa: F401
    PlayerElementEssenceModel,
)
from app.infrastructure.db.repositories.element_affinity_repository import (
    ElementAffinityRepository,
)
from app.infrastructure.db.repositories.element_essence_repository import (
    ElementEssenceRepository,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            PlayerModel.__table__,
            PlayerElementAffinityModel.__table__,
            PlayerElementEssenceModel.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    s.add(PlayerModel(id=1, discord_id=1, username="u", display_name="U"))
    s.commit()
    yield s
    s.close()


def _award(session, mob_element, per_kill):
    return EncounterService._award_element_essences(
        essence_repository=ElementEssenceRepository(session),
        affinity_repository=ElementAffinityRepository(session),
        progression_service=ElementAffinityProgressionService(),
        player_id=1,
        mob=SimpleNamespace(element=mob_element, family="x"),
        essences_per_kill=per_kill,
    )


def test_essence_drop_raises_affinity_and_carries_leftover(session):
    # 1er kill mob feu, zone à 2 essences : 0→1 (coût 1), reste 1.
    gains = _award(session, "feu", 2)
    assert len(gains) == 1
    g = gains[0]
    assert g.element == "feu" and g.essences_gained == 2
    assert g.affinity_before == 0 and g.affinity_after == 1 and g.leveled_up
    assert ElementAffinityRepository(session).get_affinities(1)["feu"] == 1
    assert ElementEssenceRepository(session).get_essences(1)["feu"] == 1

    # 2e kill : affinité 1, essences 1, +2 = 3 ; 1→2 (coût 2), reste 1.
    gains2 = _award(session, "feu", 2)
    assert gains2[0].affinity_after == 2
    assert ElementEssenceRepository(session).get_essences(1)["feu"] == 1


def test_neutral_mob_gives_nothing(session):
    assert _award(session, "", 2) == []
    assert ElementEssenceRepository(session).get_essences(1)["feu"] == 0


def test_multi_element_mob_awards_each_element(session):
    gains = _award(session, "feu,glace", 1)
    elems = {g.element for g in gains}
    assert elems == {"feu", "glace"}
    essences = ElementEssenceRepository(session).get_essences(1)
    # 1 essence chacun : 0→1 (coût 1), reste 0 pour les deux.
    affinities = ElementAffinityRepository(session).get_affinities(1)
    assert affinities["feu"] == 1 and affinities["glace"] == 1
    assert essences["feu"] == 0 and essences["glace"] == 0
