"""Database engine and request-scoped SQLAlchemy sessions."""

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./radar.db")
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
elif DATABASE_URL.startswith("postgresql+psycopg://"):
    # Supabase's shared transaction pooler does not support server-side prepared statements.
    _connect_args = {"prepare_threshold": None}
else:
    _connect_args = {}

_poolclass = NullPool if "pooler.supabase.com" in DATABASE_URL else None
_engine_options = {"poolclass": _poolclass} if _poolclass else {}
engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    **_engine_options,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base class for persisted API records."""


def get_session() -> Generator[Session, None, None]:
    """Yield one database session per API request and always close it."""

    with SessionLocal() as session:
        yield session
