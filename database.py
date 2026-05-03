"""
Database — SQLAlchemy 2.0 engine + session factory.

Active uniquement si DATABASE_URL est défini dans l'environnement.
Fallback automatique sur le stockage en mémoire si DATABASE_URL absent.

Usage:
    from database import init_db, get_session, is_db_available

    init_db()                         # au démarrage
    with get_session() as session:    # dans une requête
        session.add(...)
"""
import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text, event as sa_event
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine   = None
_Session  = None
_db_url   = None


def init_db(url: str = None, echo: bool = False, create_tables: bool = True) -> bool:
    """
    Initialise l'engine SQLAlchemy et (optionnellement) crée les tables.
    Retourne True si la connexion a réussi, False sinon.
    """
    global _engine, _Session, _db_url
    from config import Config
    db_url = url or Config.DATABASE_URL
    if not db_url:
        logger.info("DATABASE_URL non défini — mode stockage en mémoire actif")
        return False

    connect_args = {}
    pool_kwargs  = {}
    if db_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        pool_kwargs  = {"pool_pre_ping": True}
    else:
        pool_kwargs  = {
            "pool_pre_ping": True,
            "pool_size":     5,
            "max_overflow":  10,
            "pool_timeout":  30,
            "pool_recycle":  1800,
        }

    try:
        _engine  = create_engine(db_url, echo=echo,
                                  connect_args=connect_args, **pool_kwargs)
        _Session = sessionmaker(bind=_engine, autoflush=False,
                                autocommit=False, expire_on_commit=False)
        _db_url  = db_url

        if create_tables:
            from models import orm_models as _  # noqa — enregistre les modèles
            Base.metadata.create_all(_engine)
            logger.info("Tables créées / vérifiées dans la base de données")

        # Test de connexion
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        display = db_url.split("@")[-1] if "@" in db_url else db_url.split("///")[-1]
        logger.info("Base de données connectée : %s", display)
        return True

    except Exception as exc:
        logger.error("Impossible de se connecter à la base de données : %s", exc)
        _engine  = None
        _Session = None
        return False


def is_db_available() -> bool:
    """Retourne True si la DB est initialisée et accessible."""
    if _engine is None:
        return False
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_engine():
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager qui fournit une session SQLAlchemy avec auto-commit/rollback."""
    if _Session is None:
        raise RuntimeError(
            "Base de données non initialisée — appeler init_db() au démarrage "
            "ou vérifier DATABASE_URL")
    session: Session = _Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def db_health() -> dict:
    """Retourne le statut de la base de données pour /health."""
    if _engine is None:
        return {"available": False, "mode": "in-memory", "url": None}
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        display = _db_url.split("@")[-1] if "@" in _db_url else _db_url.split("///")[-1]
        return {
            "available": True,
            "mode":      "postgresql" if "postgresql" in _db_url else "sqlite",
            "url":       display,
        }
    except Exception as exc:
        return {"available": False, "mode": "error", "error": str(exc)}
