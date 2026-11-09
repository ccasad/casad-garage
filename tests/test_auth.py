import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse

from app.invites import create_invite
from app.main import app
from app.models import AuditEvent, AuthChallenge, Invite, Passkey, User, UserSession, utcnow
from app.routes import auth
from app.sessions import SESSION_COOKIE
from tests.conftest import sign_in


def events(db) -> list[str]:
    db.expire_all()
    return [e.event for e in db.scalars(select(AuditEvent).order_by(AuditEvent.id))]


@pytest.fixture
def fake_registration(monkeypatch):
    """Stand in for the authenticator: accept any registration response."""
    calls = []

    def verify(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            credential_id=b"credential-1",
            credential_public_key=b"public-key",
            sign_count=0,
            credential_backed_up=True,
        )

    monkeypatch.setattr(auth, "verify_registration_response", verify)
    return calls


def add_passkey(db, user, credential_id=b"credential-1") -> Passkey:
    passkey = Passkey(user_id=user.id, credential_id=credential_id, public_key=b"public-key")
    db.add(passkey)
    db.commit()
    return passkey


# --- Access control -------------------------------------------------------


def test_pages_redirect_to_login_when_signed_out(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_htmx_requests_get_hx_redirect(client):
    response = client.get("/", headers={"HX-Request": "true"})

    assert response.status_code == 204
    assert response.headers["hx-redirect"] == "/login"


def test_login_page_has_no_navigation(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert 'data-passkey="login"' in response.text
    assert 'aria-label="Main"' not in response.text


def test_signed_in_user_skips_login_page(client, db, member):
    sign_in(client, db, member)

    response = client.get("/login", follow_redirects=False)

    assert response.headers["location"] == "/"


def test_idle_session_expires_after_30_minutes(client, db, member):
    session = sign_in(client, db, member)
    session.last_seen_at = utcnow() - timedelta(minutes=31)
    db.commit()

    response = client.get("/", follow_redirects=False)

    assert response.headers["location"] == "/login"
    assert db.scalar(select(UserSession)) is None


def test_activity_extends_idle_session(client, db, member):
    session = sign_in(client, db, member)
    session.last_seen_at = utcnow() - timedelta(minutes=29)
    db.commit()

    assert client.get("/").status_code == 200
    db.refresh(session)
    assert utcnow() - session.last_seen_at < timedelta(minutes=1)


def test_cross_origin_posts_are_rejected(client):
    response = client.post("/auth/login/options", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403


def test_logout_ends_session(client, db, member):
    sign_in(client, db, member)

    response = client.post("/logout", follow_redirects=False)

    assert response.headers["location"] == "/login"
    assert db.scalar(select(UserSession)) is None
    assert client.get("/", follow_redirects=False).status_code == 303
    assert events(db) == ["sign_out"]


# --- Passkey setup from an invite ------------------------------------------


def test_register_options_reject_unknown_invite(client):
    response = client.post("/auth/register/options", json={"invite_token": "nope"})

    assert response.status_code == 400
    assert "invalid" in response.json()["error"]


def test_register_options_require_discoverable_verified_passkey(client, db):
    token = create_invite(db, email="New@Example.com", display_name="New")
    db.commit()

    response = client.post("/auth/register/options", json={"invite_token": token})

    body = response.json()
    assert response.status_code == 200
    assert body["display_name"] == "New"
    assert body["options"]["rp"]["id"] == "localhost"
    assert body["options"]["user"]["name"] == "new@example.com"
    assert body["options"]["authenticatorSelection"]["residentKey"] == "required"
    assert body["options"]["authenticatorSelection"]["userVerification"] == "required"
    assert db.get(AuthChallenge, uuid.UUID(body["challenge_id"])) is not None


def test_register_verify_creates_account_and_signs_in(client, db, fake_registration):
    token = create_invite(db, email="new@example.com", display_name="New")
    db.commit()
    start = client.post("/auth/register/options", json={"invite_token": token}).json()

    response = client.post(
        "/auth/register/verify",
        json={
            "challenge_id": start["challenge_id"],
            "credential": {"response": {"transports": ["internal", "hybrid"]}},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"redirect": "/"}
    assert SESSION_COOKIE in response.cookies
    assert fake_registration[0]["expected_origin"] == "http://localhost:8000"
    assert fake_registration[0]["require_user_verification"] is True

    user = db.scalar(select(User).where(User.email == "new@example.com"))
    assert user.role == "member"
    assert user.id.bytes == bytes.fromhex(_b64_to_hex(start["options"]["user"]["id"]))
    assert [p.transports for p in user.passkeys] == [["internal", "hybrid"]]
    assert db.scalar(select(Invite)) is None  # used invites are deleted
    assert events(db) == ["invite_created", "passkey_registered", "sign_in"]
    assert client.get("/").status_code == 200


def test_invite_works_only_once(client, db, fake_registration):
    token = create_invite(db, email="new@example.com", display_name="New")
    db.commit()
    start = client.post("/auth/register/options", json={"invite_token": token}).json()
    client.post(
        "/auth/register/verify", json={"challenge_id": start["challenge_id"], "credential": {}}
    )

    response = client.post("/auth/register/options", json={"invite_token": token})

    assert response.status_code == 400


def test_challenge_cannot_be_replayed(client, db, fake_registration):
    token = create_invite(db, email="new@example.com", display_name="New")
    db.commit()
    start = client.post("/auth/register/options", json={"invite_token": token}).json()
    payload = {"challenge_id": start["challenge_id"], "credential": {}}
    client.post("/auth/register/verify", json=payload)

    assert client.post("/auth/register/verify", json=payload).status_code == 400


def test_expired_invite_is_rejected(client, db):
    token = create_invite(db, email="new@example.com", display_name="New")
    db.scalar(select(Invite)).expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    assert client.post("/auth/register/options", json={"invite_token": token}).status_code == 400


def test_invite_for_existing_email_adds_a_passkey(client, db, member, fake_registration):
    add_passkey(db, member, credential_id=b"old-phone")
    token = create_invite(db, email=member.email, display_name=member.display_name)
    db.commit()
    start = client.post("/auth/register/options", json={"invite_token": token}).json()
    excluded = [c["id"] for c in start["options"]["excludeCredentials"]]

    client.post(
        "/auth/register/verify", json={"challenge_id": start["challenge_id"], "credential": {}}
    )

    assert excluded == [bytes_to_base64url(b"old-phone")]
    db.expire_all()
    assert db.scalar(select(User).where(User.email == member.email)).id == member.id
    assert len(db.scalars(select(Passkey)).all()) == 2


# --- Passkey sign-in --------------------------------------------------------


def test_login_with_unknown_passkey_fails(client, db):
    start = client.post("/auth/login/options").json()

    response = client.post(
        "/auth/login/verify",
        json={"challenge_id": start["challenge_id"], "credential": {"rawId": "AAAA"}},
    )

    assert response.status_code == 400
    assert events(db) == ["sign_in_failed"]


def test_login_with_known_passkey_signs_in(client, db, member, monkeypatch):
    passkey = add_passkey(db, member)
    monkeypatch.setattr(
        auth,
        "verify_authentication_response",
        lambda **kwargs: SimpleNamespace(new_sign_count=5),
    )
    start = client.post("/auth/login/options").json()
    assert start["options"]["userVerification"] == "required"

    response = client.post(
        "/auth/login/verify",
        json={
            "challenge_id": start["challenge_id"],
            "credential": {"rawId": bytes_to_base64url(b"credential-1")},
        },
    )

    assert response.status_code == 200
    db.refresh(passkey)
    assert passkey.sign_count == 5
    assert passkey.last_used_at is not None
    assert events(db) == ["sign_in"]
    assert client.get("/").status_code == 200


def test_login_with_bad_signature_fails(client, db, member, monkeypatch):
    add_passkey(db, member)

    def reject(**kwargs):
        raise InvalidAuthenticationResponse("bad signature")

    monkeypatch.setattr(auth, "verify_authentication_response", reject)
    start = client.post("/auth/login/options").json()

    response = client.post(
        "/auth/login/verify",
        json={
            "challenge_id": start["challenge_id"],
            "credential": {"rawId": bytes_to_base64url(b"credential-1")},
        },
    )

    assert response.status_code == 400
    assert SESSION_COOKIE not in response.cookies
    assert events(db) == ["sign_in_failed"]


def _b64_to_hex(value: str) -> str:
    import base64

    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).hex()


def test_signing_in_clears_stale_sessions(client, db, member, monkeypatch):
    stale = sign_in(TestClient(app), db, member)
    stale.last_seen_at = utcnow() - timedelta(hours=2)
    db.commit()
    stale_id = stale.id
    add_passkey(db, member)
    monkeypatch.setattr(
        auth, "verify_authentication_response", lambda **kwargs: SimpleNamespace(new_sign_count=1)
    )
    start = client.post("/auth/login/options").json()

    client.post(
        "/auth/login/verify",
        json={
            "challenge_id": start["challenge_id"],
            "credential": {"rawId": bytes_to_base64url(b"credential-1")},
        },
    )

    db.expire_all()
    sessions = db.scalars(select(UserSession)).all()
    assert len(sessions) == 1
    assert sessions[0].id != stale_id


def test_invite_tokens_survive_messaging_apps(db):
    token = create_invite(db, email="new@example.com", display_name="New")

    # Hex only: no `_` or `-` for chat apps to turn into italics or drop from a link.
    assert len(token) == 64
    assert set(token) <= set("0123456789abcdef")
