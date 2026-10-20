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


def _set_talent(session, element, talent, cap=100):
    """Talent imposé (sinon tiré au hasard à la création)."""
    repo = ElementAffinityRepository(session)
    repo.ensure_talents(1)
    row = repo._rows(1)[element]
    row.talent, row.affinity_cap = talent, cap
    session.commit()


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
    # Talent 10 = +100 % : une zone à 1 essence en donne 2.
    _set_talent(session, "feu", 10)
    gains = _award(session, "feu", 1)
    assert len(gains) == 1
    g = gains[0]
    assert g.element == "feu" and g.essences_gained == 2
    # 0→1 (coût 1), reste 1.
    assert g.affinity_before == 0 and g.affinity_after == 1 and g.leveled_up
    assert ElementAffinityRepository(session).get_affinities(1)["feu"] == 1
    assert ElementEssenceRepository(session).get_essences(1)["feu"] == 1

    # 2e kill : essences 1 + 2 = 3 ; 1→2 (coût 2), reste 1.
    gains2 = _award(session, "feu", 1)
    assert gains2[0].affinity_after == 2
    assert ElementEssenceRepository(session).get_essences(1)["feu"] == 1


def test_un_element_mort_ne_gagne_jamais_d_essence(session):
    _set_talent(session, "feu", 0)
    assert _award(session, "feu", 3) == []
    assert ElementAffinityRepository(session).get_affinities(1)["feu"] == 0


def test_l_affinite_s_arrete_au_plafond_de_l_element(session):
    _set_talent(session, "feu", 10, cap=100)
    for _ in range(200):
        _award(session, "feu", 100)
    assert ElementAffinityRepository(session).get_affinities(1)["feu"] == 100
    _set_talent(session, "feu", 10, cap=300)
    for _ in range(400):
        _award(session, "feu", 100)
    assert ElementAffinityRepository(session).get_affinities(1)["feu"] == 300


def test_tout_le_monde_part_de_zero(session):
    ElementAffinityRepository(session).ensure_talents(1)
    assert set(ElementAffinityRepository(session).get_affinities(1).values()) == {0}


def test_neutral_mob_gives_nothing(session):
    assert _award(session, "", 2) == []
    assert ElementEssenceRepository(session).get_essences(1)["feu"] == 0


def test_essences_range_parsing():
    from app.infrastructure.encounters.farm_zone_loader import _essences_range_from_entry

    # Nouveau format min/max
    assert _essences_range_from_entry({"essences_min": 1, "essences_max": 3}, 1, 1) == (1, 3)
    # min seul → max = min
    assert _essences_range_from_entry({"essences_min": 2}, 1, 1) == (2, 2)
    # Ancien format fixe → min == max
    assert _essences_range_from_entry({"essences_per_kill": 2}, 1, 1) == (2, 2)
    # Rien → défauts
    assert _essences_range_from_entry({}, 1, 3) == (1, 3)
    # max < min corrigé (hi >= lo)
    assert _essences_range_from_entry({"essences_min": 3, "essences_max": 1}, 1, 1) == (3, 3)


def test_multi_element_mob_awards_each_element(session):
    _set_talent(session, "feu", 10)
    _set_talent(session, "glace", 10)
    gains = _award(session, "feu,glace", 1)
    assert {g.element for g in gains} == {"feu", "glace"}
    affinities = ElementAffinityRepository(session).get_affinities(1)
    essences = ElementEssenceRepository(session).get_essences(1)
    # 2 essences chacun (talent 10) : 0→1 (coût 1), reste 1 pour les deux.
    assert affinities["feu"] == 1 and affinities["glace"] == 1
    assert essences["feu"] == 1 and essences["glace"] == 1
