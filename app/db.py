from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from app.config import get_settings


def sqlalchemy_url(url: str) -> str:
    """Neon hands out postgresql:// URLs; SQLAlchemy needs the psycopg 3 driver named."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(
        sqlalchemy_url(url),
        # Neon's pooler does the real pooling; keep a small local pool per function
        # instance and check connections first, since Neon suspends idle computes.
        pool_size=2,
        max_overflow=3,
        pool_pre_ping=True,
        pool_recycle=300,
        # The pooler runs PgBouncer in transaction mode, so skip server-side prepares.
        connect_args={"prepare_threshold": None},
    )


def get_db() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as db:
        yield db
