"""Surveillance : le journal est complet par construction (chaque mouvement
d'or, chaque niveau), ne casse jamais le jeu, et l'or apparu hors du jeu est
détecté."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.application.monitoring import alerting, dataset
from app.application.monitoring.snapshots import take_snapshots
from app.application.use_cases.reset_player import ResetPlayerUseCase
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.monitoring_model import GameEventModel, PlayerDailySnapshotModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.monitoring.telemetry import InteractionBuffer, record
from tests.infrastructure.test_use_consumable import session  # noqa: F401


def _new(session, discord_id=7) -> int:
    return PlayerRepository(session).get_or_create_by_discord_id(discord_id, "u", "U").player.id


def _events(session, kind):
    return session.execute(select(GameEventModel).where(GameEventModel.kind == kind)
                           .order_by(GameEventModel.id)).scalars().all()


def test_chaque_mouvement_d_or_est_journalise_avec_sa_source(session):
    pid = _new(session)
    repo = PlayerRepository(session)
    repo.add_gold(pid, 500, source="combat")
    repo.add_gold(pid, -800, source="boutique")      # plancher à 0 : seuls 500 partent
    repo.add_gold(pid, 0, source="quete")              # rien ne bouge : rien n'est écrit
    repo.add_gold(pid, 40)                             # source oubliée : « autre »
    repo.set_gold(pid, 1000)                           # l'admin
    assert [(e.ref, e.gold) for e in _events(session, "gold")] == [
        ("combat", 500), ("boutique", -500), ("autre", 40), ("admin", 960)]


def test_les_niveaux_sont_journalises_et_ceux_de_l_admin_marques(session):
    pid = _new(session)
    repo = PlayerRepository(session)
    repo.apply_progression(pid, 3, 0, 2)
    repo.apply_progression(pid, 3, 50, 2)              # même niveau : rien
    repo.apply_progression(pid, 10, 0, 9, source="admin")
    ups = _events(session, "level_up")
    assert [(e.qty, e.data) for e in ups] == [(3, '{"from":1}'), (10, '{"from":3,"src":"admin"}')]


def test_sans_la_table_du_journal_le_jeu_continue():
    engine = create_engine("sqlite:///:memory:")
    tables = [t for t in Base.metadata.sorted_tables if t.name != "game_events"]
    Base.metadata.create_all(engine, tables=tables)
    s = sessionmaker(bind=engine)()
    try:
        pid = _new(s)
        PlayerRepository(s).add_gold(pid, 300, source="combat")
        record(s, "combat", player_id=pid)
        s.commit()
        assert s.get(PlayerResourceModel, pid).gold == 300
    finally:
        s.close()
        engine.dispose()


def test_tampon_des_interactions(session):
    pid = _new(session, discord_id=42)
    buffer = InteractionBuffer()
    buffer.push(42, "profil")
    buffer.push(999, "demarrer")                        # pas encore de profil
    buffer.push(42, "boss moi", kind="error")
    assert buffer.flush(session) == 3 and len(buffer) == 0
    rows = session.execute(select(GameEventModel.kind, GameEventModel.player_id, GameEventModel.discord_id,
                                  GameEventModel.ref).order_by(GameEventModel.id)).all()
    assert rows == [("interaction", pid, 42, "profil"), ("interaction", None, 999, "demarrer"),
                    ("error", pid, 42, "boss moi")]


def test_l_or_apparu_hors_du_jeu_est_detecte(session):
    pid = _new(session)
    repo = PlayerRepository(session)
    repo.add_gold(pid, 1000, source="combat")
    assert take_snapshots(session) == 1
    repo.add_gold(pid, 250, source="quete")             # après la photo : expliqué par le journal
    ds = dataset.load(session, days=7)
    gold = [e for e in ds.events if e.kind == "gold"]
    assert alerting.unexplained_gold(ds, pid, gold) == 0
    # De l'or posé directement en base, sans passer par le jeu :
    session.get(PlayerResourceModel, pid).gold += 50_000
    session.commit()
    ds = dataset.load(session, days=7)
    gold = [e for e in ds.events if e.kind == "gold"]
    assert alerting.unexplained_gold(ds, pid, gold) == 50_000
    found = alerting.compute(ds)
    assert any(a.code == "unexplained_gold" and a.player_id == pid for a in found)


def test_historique_des_alertes_et_sourdine(session):
    pid = _new(session)
    session.get(PlayerResourceModel, pid).gold = 10                # aucun mouvement enregistré…
    take_snapshots(session)
    session.get(PlayerResourceModel, pid).gold = 90_000            # …puis 90 000 or surgissent
    session.commit()
    current = alerting.compute(dataset.load(session, days=7))
    fresh = alerting.sync(session, current)
    assert fresh and alerting.sync(session, current) == []          # vue une seule fois
    key = next(a.key for a in current if a.code == "unexplained_gold")
    assert key in {r.key for r in alerting.to_notify(session)}
    alerting.mute(session, key, 7)
    assert key not in {r.key for r in alerting.to_notify(session)}
    alerting.sync(session, [])                                      # disparue : résolue
    assert alerting.history(session)[0].key == key


def test_le_reset_d_un_joueur_purge_son_journal(session):
    pid = _new(session)
    PlayerRepository(session).add_gold(pid, 10, source="combat")
    take_snapshots(session)
    ResetPlayerUseCase().execute(session, pid)
    session.commit()
    assert not _events(session, "gold")
    assert session.execute(select(PlayerDailySnapshotModel)).first() is None


def test_les_joueurs_arrives_avant_le_journal_ne_faussent_pas_la_retention(session):
    from datetime import UTC, datetime, timedelta

    from app.infrastructure.db.models.player_model import PlayerModel

    old = _new(session, discord_id=1)
    session.get(PlayerModel, old).created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=60)
    session.commit()
    record(session, "interaction", player_id=old, ref="profil")    # le journal commence aujourd'hui
    new = _new(session, discord_id=2)
    session.commit()
    ds = dataset.load(session, days=30)
    assert set(ds.arrivals()) == {new}
