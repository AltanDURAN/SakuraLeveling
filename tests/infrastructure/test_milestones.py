"""Les premières fois d'un joueur ne s'annoncent qu'une fois (14/11/2026)."""

from app.application.services import milestones
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from tests.infrastructure.test_use_consumable import session  # noqa: F401


def test_une_premiere_fois_ne_compte_qu_une_fois_par_joueur_et_par_jalon(session):
    a = PlayerRepository(session).get_or_create_by_discord_id(1, "a", "A").player.id
    b = PlayerRepository(session).get_or_create_by_discord_id(2, "b", "B").player.id
    assert milestones.claim(session, a, milestones.FIRST_EPIC)
    session.commit()
    assert not milestones.claim(session, a, milestones.FIRST_EPIC)        # déjà annoncée
    assert milestones.claim(session, a, milestones.FIRST_ELITE)           # un autre jalon
    assert milestones.claim(session, b, milestones.FIRST_EPIC)            # un autre joueur
    assert {"epic", "legendary", "mythic"} == set(milestones.EPIC_OR_BETTER)
