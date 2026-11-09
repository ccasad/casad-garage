import os

# Pin settings before the app loads them, and blank DATABASE_URL so tests can
# never reach a real database (environment variables override .env).
os.environ.update(
    APP_BASE_URL="http://localhost:8000",
    WEBAUTHN_RP_ID="localhost",
    DATABASE_URL="",
    ADMIN_EMAIL="admin@example.com",
    # A fixed test-only Fernet key (32 zero bytes, base64)
    TOKEN_ENCRYPTION_KEY="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import storage
from app.db import get_db
from app.main import app
from app.models import Base, User, UserSession, utcnow
from app.security import hash_token, new_token
from app.sessions import ABSOLUTE_LIFETIME, SESSION_COOKIE

ORIGIN = "http://localhost:8000"


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client(engine):
    def test_db():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    with TestClient(app, headers={"Origin": ORIGIN}) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_user(db, *, email="member@example.com", name="Member", role="member") -> User:
    user = User(email=email, display_name=name, role=role)
    db.add(user)
    db.commit()
    return user


def sign_in(client, db, user) -> UserSession:
    token = new_token()
    now = utcnow()
    session = UserSession(
        token_hash=hash_token(token),
        user_id=user.id,
        created_at=now,
        last_seen_at=now,
        expires_at=now + ABSOLUTE_LIFETIME,
    )
    db.add(session)
    db.commit()
    client.cookies.set(SESSION_COOKIE, token)
    return session


@pytest.fixture
def member(db):
    return make_user(db)


@pytest.fixture
def admin(db):
    return make_user(db, email="admin@example.com", name="Admin", role="admin")


def make_car(db, owner, *, visibility="shared", year=2019, make="Acme", model="Roadster", **extra):
    from app.crypto import blind_index
    from app.models import Car

    vin = extra.get("vin")
    car = Car(
        added_by_id=owner.id,
        visibility=visibility,
        year=year,
        make=make,
        model=model,
        vin_hash=blind_index(vin) if vin else None,
        **extra,
    )
    db.add(car)
    db.commit()
    return car


class MemoryBackend:
    """Files in a dict, standing in for Vercel Blob."""

    def __init__(self):
        self.files: dict[str, bytes] = {}

    def put(self, pathname, data, content_type):
        self.files[pathname] = data
        return pathname

    def get(self, ref):
        try:
            return self.files[ref]
        except KeyError as exc:
            raise storage.StorageError("missing") from exc

    def delete(self, ref):
        self.files.pop(ref, None)


@pytest.fixture(autouse=True)
def files(monkeypatch) -> MemoryBackend:
    backend = MemoryBackend()
    monkeypatch.setattr(storage, "backend", lambda: backend)
    return backend
