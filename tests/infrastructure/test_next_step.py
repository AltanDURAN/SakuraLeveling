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


def test_l_epreuve_est_rappelee_des_que_la_puissance_est_la(session, monkeypatch):
    """En bêta (20/11/2026), personne n'avait tenté /epreuve : la ligne le
    rappelle dès que la puissance requise est atteinte."""
    from app.application.services import next_step as ns

    pid = PlayerRepository(session).get_or_create_by_discord_id(1, "u", "U").player.id
    monkeypatch.setattr("app.application.services.combat_passives_resolver.resolve_player_power",
                        lambda *a, **k: 10 ** 6)
    assert "rang E" in next_step(session, pid) and "/epreuve" in next_step(session, pid)

    monkeypatch.setattr("app.application.services.combat_passives_resolver.resolve_player_power",
                        lambda *a, **k: 1)
    assert "/epreuve" not in (next_step(session, pid) or "")            # pas encore la puissance
