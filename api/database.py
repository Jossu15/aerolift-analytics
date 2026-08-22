"""
Database setup - SQLAlchemy engine/session.

The connection string comes from the DATABASE_URL environment variable,
defaulting to a local SQLite file so the stack runs with zero infra:

    export DATABASE_URL=postgresql://user:pass@host:5432/aerolift
    (requires psycopg2-binary installed)

Every table is created via init_db() on application startup.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DEFAULT_DB_URL = "sqlite:///./aerolift.db"


def get_database_url():
    return os.environ.get("DATABASE_URL", DEFAULT_DB_URL)


engine = create_engine(
    get_database_url(),
    connect_args={"check_same_thread": False}
    if get_database_url().startswith("sqlite") else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                            future=True)
Base = declarative_base()


def get_db():
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from api import models  # noqa: F401 - register mappers before create_all
    Base.metadata.create_all(bind=engine)
