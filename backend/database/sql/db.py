"""SQLAlchemy session/engine bootstrap for the local SQL persistence layer.

Active when ``DB_PROVIDER=sqlite``. Other providers (Postgres) reuse the same
session machinery by changing ``SQLITE_PATH`` / connection string.
"""

import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

SQLITE_PATH = os.environ.get("SQLITE_PATH", "./omi_local.db")
SQL_URL = os.environ.get("SQL_URL") or f"sqlite:///{SQLITE_PATH}"

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _connect_args() -> dict:
    if SQL_URL.startswith("sqlite"):
        # SQLite + multi-thread FastAPI: disable same-thread check.
        return {"check_same_thread": False}
    return {}


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(SQL_URL, future=True, connect_args=_connect_args())
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def init_db() -> None:
    """Create all tables. Idempotent — safe to call on every startup."""
    from database.sql import models  # noqa: F401 — registers ORM classes

    engine = get_engine()
    models.Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed session that commits on success, rolls back on error."""
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
