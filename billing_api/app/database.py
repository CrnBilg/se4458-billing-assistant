from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


def get_engine():
    """Engine is created lazily so tests can run without a Postgres driver."""
    global _engine
    if _engine is None:
        _engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
    return _engine


def get_db():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()
