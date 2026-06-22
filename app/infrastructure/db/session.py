from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.infrastructure.config.settings import settings


_is_sqlite = settings.database_url.startswith("sqlite")

# SQLite : 3 process écrivent la même base (bot + webapp + backup). Sans
# configuration de concurrence, un writer prend un lock exclusif et le
# moindre POST admin pendant un combat lève `database is locked`.
#   • timeout : attendre qu'un lock se libère plutôt que d'échouer aussitôt.
#   • WAL : lecteurs et un writer peuvent coexister (au lieu du verrou global
#     du mode rollback-journal par défaut).
#   • busy_timeout : idem côté pragma, pour les connexions concurrentes.
_connect_args = {"timeout": 15} if _is_sqlite else {}

engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args=_connect_args,
)


if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


@contextmanager
def get_db_session():
    """Session DB avec frontière transactionnelle de DÉFENSE EN PROFONDEUR.

    Les repos commitent toujours leurs propres opérations (sémantique inchangée
    — un commit après un commit est un no-op SQLAlchemy), mais en cas
    d'exception remontant ici, on rollback explicitement les changements
    non-commités avant de fermer. Avant : la session se fermait sans rollback
    et la prochaine session pouvait hériter d'un état zombie (cf. audit A1).
    """
    session = SessionLocal()
    try:
        yield session
    except Exception:
        # Rollback explicite : un session.close() seul n'annule pas une
        # transaction en cours d'écriture côté SQLAlchemy.
        try:
            session.rollback()
        except Exception:
            pass
        raise
    finally:
        session.close()