"""Database engine / session setup.

Reads DB_PATH from the environment (via .env). Phase 2 introduces a richer
`backend.config` module; this module intentionally stays dependency-light so it
can be imported very early (e.g. by init_db.py) without pulling in YAML config.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.db.models import Base

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./data/jobs.db")


def _ensure_parent_dir(path: str) -> None:
    parent = Path(path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


_ensure_parent_dir(DB_PATH)

# check_same_thread=False lets the SQLite connection be shared across FastAPI's
# threadpool and the APScheduler worker thread.
engine = create_engine(
    f"sqlite:///{Path(DB_PATH).expanduser().resolve()}",
    connect_args={"check_same_thread": False},
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def init_db() -> None:
    """Create all tables if they do not already exist."""
    _ensure_parent_dir(DB_PATH)
    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
