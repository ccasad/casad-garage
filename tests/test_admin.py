from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Invite, Passkey, User, UserSession
from tests.conftest import make_user, sign_in


def test_members_cannot_manage_people(client, db, member):
    sign_in(client, db, member)

    assert client.get("/admin/people").status_code == 403
    assert "/admin/people" not in client.get("/more").text


def test_admin_creates_invite_and_sees_link_once(client, db, admin):
    sign_in(client, db, admin)

    response = client.post(
        "/admin/invites", data={"email": " Kid@Example.com ", "display_name": "Kid"}
    )

    assert response.status_code == 200
    assert "http://localhost:8000/invite#" in response.text
    invite = db.scalar(select(Invite))
    assert (invite.email, invite.role, invite.created_by_id) == (
        "kid@example.com",
        "member",
        admin.id,
    )
    assert "/invite#" not in client.get("/admin/people").text


def test_admin_revokes_invite(client, db, admin):
    sign_in(client, db, admin)
    client.post("/admin/invites", data={"email": "kid@example.com", "display_name": "Kid"})
    invite = db.scalar(select(Invite))

    invite_id = invite.id

    client.post(f"/admin/invites/{invite_id}/revoke")

    db.expire_all()
    assert db.get(Invite, invite_id) is None  # no name or email left behind


def test_admin_removes_user_with_passkeys_and_sessions(client, db, admin):
    other = make_user(db, email="kid@example.com", name="Kid")
    db.add(Passkey(user_id=other.id, credential_id=b"kid-phone", public_key=b"pk"))
    db.commit()
    sign_in(TestClient(app), db, other)
    sign_in(client, db, admin)

    other_id = other.id

    response = client.post(f"/admin/users/{other_id}/remove", follow_redirects=False)

    assert response.status_code == 303
    db.expire_all()
    assert db.get(User, other_id) is None
    assert db.scalars(select(Passkey)).all() == []
    assert [s.user_id for s in db.scalars(select(UserSession))] == [admin.id]


def test_admin_cannot_remove_self(client, db, admin):
    sign_in(client, db, admin)

    assert client.post(f"/admin/users/{admin.id}/remove").status_code == 400
