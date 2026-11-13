"""Deux actions lancées ensemble ne lisent jamais le même état (13/11/2026).

Beaucoup de boutons font leur travail dans un thread, avec leur propre
connexion : deux clics = deux threads. SQLite ne commençait sa transaction
qu'à la première ÉCRITURE — les deux lisaient donc le même état (deux copies,
un point à placer, une récompense à prendre), puis écrivaient l'un après
l'autre. Reproduit avant correction : fusion faite deux fois avec deux copies
(47 courses sur 100), récompense de la tour payée deux fois (36 sur 200),
deux points de stats placés avec un seul (17 sur 200).

Ces tests tournent sur une base FICHIER en WAL, réglée comme la production,
avec de vrais threads (une base en mémoire partage une seule connexion et ne
montre rien)."""

import importlib
import pkgutil
import threading
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.infrastructure.db.models as models_pkg
from app.infrastructure.db.base import Base
from app.infrastructure.db.models.progression_model import PlayerProgressionModel
from app.infrastructure.db.models.resource_model import PlayerResourceModel
from app.infrastructure.db.repositories.player_repository import PlayerRepository
from app.infrastructure.db.unit_of_work import atomic

for _mod in pkgutil.iter_modules(models_pkg.__path__):
    importlib.import_module(f"{models_pkg.__name__}.{_mod.name}")


@pytest.fixture
def Session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jeu.db'}", connect_args={"timeout": 15})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


def _player(Session, gold=0, stat_points=0) -> int:
    with Session() as s:
        pid = PlayerRepository(s).get_or_create_by_discord_id(1, "u", "U").player.id
        s.get(PlayerResourceModel, pid).gold = gold
        s.get(PlayerProgressionModel, pid).stat_points = stat_points
        s.commit()
        return pid


def _gold(Session, pid) -> int:
    with Session() as s:
        return s.get(PlayerResourceModel, pid).gold


def test_un_second_bloc_atomique_attend_la_fin_du_premier(Session):
    order: list[str] = []
    inside, release = threading.Event(), threading.Event()

    def first():
        with Session() as s, atomic(s):
            order.append("1 entre")
            inside.set()
            release.wait(5)
            order.append("1 sort")

    def second():
        inside.wait(5)
        with Session() as s, atomic(s):
            order.append("2 entre")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    inside.wait(5)
    threads[1].join(0.3)                       # le second est bloqué à l'entrée…
    assert order == ["1 entre"]
    release.set()                              # …jusqu'à ce que le premier sorte
    for t in threads:
        t.join(5)
    assert order == ["1 entre", "1 sort", "2 entre"]


def test_ce_qui_a_ete_lu_avant_le_verrou_est_relu(Session):
    """Une vérification faite sur un état lu AVANT le verrou serait périmée."""
    pid = _player(Session, gold=100)
    with Session() as mine:
        assert mine.get(PlayerResourceModel, pid).gold == 100          # lu, gardé par la session
        with Session() as other:                                      # pendant ce temps, ailleurs
            PlayerRepository(other).add_gold(pid, -100, source="boutique")
        with atomic(mine):
            assert mine.get(PlayerResourceModel, pid).gold == 0       # relu sous le verrou


def test_le_verrou_ne_perd_jamais_une_ecriture_en_attente(Session):
    pid = _player(Session, gold=100)
    with Session() as s:
        s.get(PlayerResourceModel, pid).gold = 250                    # modifié, pas encore envoyé
        with atomic(s):
            assert s.get(PlayerResourceModel, pid).gold == 250
    assert _gold(Session, pid) == 250


def test_une_ecriture_d_or_n_ecrase_pas_celle_d_un_autre_thread(Session):
    """`add_gold` lit puis écrit : sans verrou pris avant la lecture, deux
    dépenses simultanées n'en faisaient qu'une."""
    pid = _player(Session, gold=10_000)
    rounds, threads_per_round = 20, 4
    for _ in range(rounds):
        barrier = threading.Barrier(threads_per_round)

        def spend():
            with Session() as s:
                barrier.wait(5)
                PlayerRepository(s).add_gold(pid, -10, source="boutique")

        workers = [threading.Thread(target=spend) for _ in range(threads_per_round)]
        for t in workers:
            t.start()
        for t in workers:
            t.join(10)
    assert _gold(Session, pid) == 10_000 - 10 * rounds * threads_per_round


def test_un_point_de_stats_ne_se_place_qu_une_fois(Session):
    """+ATK et +DEF cliqués ensemble avec UN point : un seul passe."""
    pid = _player(Session, stat_points=0)
    for _ in range(25):
        with Session() as s:
            progression = s.get(PlayerProgressionModel, pid)
            progression.stat_points = 1
            progression.points_attack = progression.points_defense = 0
            s.commit()
        barrier = threading.Barrier(2)
        results: list[bool] = []

        def place(target):
            with Session() as s:
                barrier.wait(5)
                results.append(PlayerRepository(s).allocate_stat_point(pid, target, 1))

        workers = [threading.Thread(target=place, args=(t,)) for t in ("attack", "defense")]
        for t in workers:
            t.start()
        for t in workers:
            t.join(10)
        with Session() as s:
            progression = s.get(PlayerProgressionModel, pid)
            assert sorted(results) == [False, True]
            assert progression.points_attack + progression.points_defense == 1
            assert progression.stat_points == 0


def test_la_recompense_du_jour_de_la_tour_n_est_payee_qu_une_fois(Session):
    from app.application.use_cases import tower
    from app.infrastructure.db.repositories.tower_repository import TowerRepository

    pid = _player(Session, gold=0)
    with Session() as s:
        TowerRepository(s).get_or_create(pid).best_floor = 30
        s.commit()
    now = datetime(2026, 12, 2, 12, 0, tzinfo=UTC)
    paid = []
    for day in range(1, 16):
        moment = now.replace(day=day)
        barrier = threading.Barrier(2)
        outcomes = []

        def claim():
            with Session() as s:
                profile = PlayerRepository(s).get_or_create_by_discord_id(1, "u", "U")
                barrier.wait(5)
                try:
                    outcomes.append(tower.claim_daily(s, profile, moment))
                except tower.TowerError as refusal:
                    outcomes.append(refusal)

        workers = [threading.Thread(target=claim) for _ in range(2)]
        for t in workers:
            t.start()
        for t in workers:
            t.join(10)
        paid.append(sum(1 for o in outcomes if not isinstance(o, Exception)))
    assert paid == [1] * 15
    assert _gold(Session, pid) == 15 * 10 * 30          # 10 or × étage record, une fois par jour
