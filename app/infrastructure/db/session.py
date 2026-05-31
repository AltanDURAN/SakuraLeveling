from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.infrastructure.config.settings import settings


engine = create_engine(settings.database_url, echo=settings.debug)

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