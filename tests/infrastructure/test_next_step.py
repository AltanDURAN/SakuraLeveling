"""La ligne « Prochaine étape » de `/profil` : la première chose utile à faire
(décision de l'auteur, 14/11/2026)."""

from datetime import UTC, datetime, timedelta

from app.application.services.next_step import next_step
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.repositories.cooldown_repository import CooldownRepository
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from tests.infrastructure.test_use_consumable import session  # noqa: F401


def test_les_points_a_placer_passent_avant_tout(session):
    pid = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U").player.id
    progression = session.get(PlayerProgressionModel, pid)
    progression.stat_points, progression.skill_points = 2, 1
    session.commit()
    assert "2 points de stats" in next_step(session, pid) and "/stats" in next_step(session, pid)

    progression.stat_points = 0
    session.commit()
    assert "1 point d'arbre" in next_step(session, pid) and "/arbre" in next_step(session, pid)

    progression.skill_points = 0
    session.commit()
    assert "/daily" in next_step(session, pid)                 # rien à placer : la solde du jour

    assert next_step(session, 999_999) is None                  # joueur inconnu : rien, jamais d'erreur
