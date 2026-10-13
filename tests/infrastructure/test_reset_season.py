"""Reset de saison : tout repart à zéro, seule l'identité Discord reste."""

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.application.use_cases.reset_season import preview_season_reset, reset_season
from app.infrastructure.db.models.admin_command_model import AdminCommandModel  # noqa: F401
from app.infrastructure.db.models.player_model import PlayerModel
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.models.work_order_model import PlayerArtisanMasteryModel
from app.infrastructure.db.models.world_boss_model import WorldBossModel
from tests.infrastructure.test_reset_player_use_case import (  # noqa: F401
    _create_player,
    session,
)


def _count(session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def _boss(session) -> None:
    now = datetime.now(UTC)
    columns = {c.name for c in WorldBossModel.__table__.columns}
    values = {
        "code": "golem", "name": "Golem", "status": "defeated", "max_hp": 100,
        "current_hp": 0, "attack": 1, "defense": 1, "speed": 1,
        "created_at": now, "updated_at": now, "spawned_at": now,
    }
    session.add(WorldBossModel(**{k: v for k, v in values.items() if k in columns}))
    session.commit()


def test_les_points_de_stats_places_sont_remis_a_zero(session):
    """Bug corrigé : un reset gardait les points placés via /stats."""
    pid = _create_player(session, 1, "Alice")
    prog = session.get(PlayerProgressionModel, pid)
    prog.stat_points, prog.points_attack, prog.points_defense = 3, 10, 4
    session.commit()

    ResetPlayerUseCase().execute(session, pid)
    prog = session.get(PlayerProgressionModel, pid)
    assert (prog.stat_points, prog.points_attack, prog.points_defense, prog.points_max_hp) == (0, 0, 0, 0)


def test_la_maitrise_des_artisans_est_effacee(session):
    pid = _create_player(session, 1, "Alice")
    now = datetime.now(UTC)
    columns = {c.name for c in PlayerArtisanMasteryModel.__table__.columns}
    values = {"player_id": pid, "artisan_code": "forgeron", "orders_completed": 12,
              "created_at": now, "updated_at": now}
    session.add(PlayerArtisanMasteryModel(**{k: v for k, v in values.items() if k in columns}))
    session.commit()

    ResetPlayerUseCase().execute(session, pid)
    assert _count(session, PlayerArtisanMasteryModel) == 0


def test_la_saison_repart_a_zero_mais_garde_les_joueurs(session):
    a = _create_player(session, 1, "Alice")
    b = _create_player(session, 2, "Bob")
    _boss(session)

    preview = preview_season_reset(session)
    assert preview.players == 2 and preview.cleared["world_bosses"] == 1
    assert _count(session, WorldBossModel) == 1, "l'aperçu ne modifie rien"

    report = reset_season(session)

    assert report.roles_queued
    assert _count(session, PlayerModel) == 2
    assert _count(session, WorldBossModel) == 0
    for pid in (a, b):
        assert session.get(PlayerProgressionModel, pid).level == 1
        assert session.get(PlayerResourceModel, pid).gold == 0
    pending = session.execute(select(AdminCommandModel.action)).scalars().all()
    assert pending == ["reset_rank_roles"]
