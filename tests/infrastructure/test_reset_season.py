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
from app.infrastructure.db.repositories.player_repository import PlayerRepository
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


def test_la_surveillance_repart_du_lancement_de_la_saison(session):
    """Journal, photos et alertes vidés — y compris les lignes sans joueur —
    puis le repère « saison 1 » : le site admin compte depuis là, et chaque
    joueur déjà inscrit « arrive » au lancement."""
    from datetime import timedelta

    from app.application.monitoring import dataset
    from app.application.monitoring.snapshots import take_snapshots
    from app.infrastructure.db.models.monitoring_model import (
        GameEventModel,
        MonitoringAlertModel,
        PlayerDailySnapshotModel,
    )
    from app.infrastructure.monitoring.telemetry import record

    a = _create_player(session, 1, "Alice")
    session.get(PlayerModel, a).created_at = datetime.now(UTC) - timedelta(days=40)
    PlayerRepository(session).add_gold(a, 500, source="combat")
    record(session, "flee", zone="123", ref="slime")                       # sans joueur
    now = datetime.now(UTC).replace(tzinfo=None)
    session.add(MonitoringAlertModel(key="dau_drop:all", code="dau_drop", severity="serieux", title="t",
                                     first_seen=now, last_seen=now))
    session.commit()
    take_snapshots(session)
    assert preview_season_reset(session).cleared["game_events"] == 2

    reset_season(session, season=1)

    rows = session.execute(select(GameEventModel.kind, GameEventModel.qty)).all()
    assert rows == [("season", 1)]
    assert _count(session, PlayerDailySnapshotModel) == 0 and _count(session, MonitoringAlertModel) == 0
    # Une ligne d'avant le lancement arrivée en retard (tampon vidé pendant le reset) : ignorée.
    record(session, "interaction", player_id=a, ref="profil", at=now - timedelta(hours=2))
    session.commit()
    ds = dataset.load(session, days=30)
    assert ds.season == 1 and ds.journal_start == ds.season_start
    assert [e.kind for e in ds.events] == ["season"]
    assert ds.players[a].started_at == ds.season_start
    assert set(ds.arrivals()) == {a}


def test_le_reset_de_saison_est_tout_ou_rien(session, monkeypatch):
    a = _create_player(session, 1, "Alice")
    _create_player(session, 2, "Bob")
    _boss(session)
    calls = []

    def flaky(self, s, player_id):
        calls.append(player_id)
        if len(calls) == 2:
            raise RuntimeError("panne au 2e joueur")
        original(self, s, player_id)

    original = ResetPlayerUseCase.execute
    monkeypatch.setattr(ResetPlayerUseCase, "execute", flaky)
    try:
        reset_season(session)
    except RuntimeError:
        pass
    session.expire_all()
    assert session.get(PlayerProgressionModel, a).level == 5, "le 1er joueur n'est pas remis à zéro seul"
    assert _count(session, WorldBossModel) == 1


def test_sauvegarde_de_la_base(tmp_path):
    import sqlite3

    import pytest

    from app.infrastructure.db.backup import BackupError, backup_sqlite

    db = tmp_path / "jeu.db"
    with sqlite3.connect(db) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE t (v INTEGER)")
        c.execute("INSERT INTO t VALUES (42)")
    copy = backup_sqlite("avant_saison_1", url=f"sqlite:///{db}")
    assert copy.parent == tmp_path and copy.name.startswith("jeu_avant_saison_1_")
    with sqlite3.connect(copy) as c:
        assert c.execute("SELECT v FROM t").fetchall() == [(42,)]
    with pytest.raises(BackupError):
        backup_sqlite("x", url="postgresql://ailleurs/jeu")
    with pytest.raises(BackupError):
        backup_sqlite("x", url=f"sqlite:///{tmp_path / 'absente.db'}")
