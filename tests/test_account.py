from sqlalchemy import func, select

from app.models import AuditEvent, Passkey, User, UserSession
from app.sessions import SESSION_COOKIE
from tests.conftest import make_user, sign_in


def count(db, model):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


def test_export_has_the_account_but_no_secrets(client, db, member):
    db.add(Passkey(user_id=member.id, credential_id=b"phone", public_key=b"secret-key"))
    db.commit()
    sign_in(client, db, member)

    response = client.get("/account/export")

    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"].startswith('attachment; filename="template-app-')
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["account"]["email"] == member.email
    assert data["account"]["passkeys"] == 1
    assert "secret-key" not in response.text
    assert [e.event for e in db.scalars(select(AuditEvent))] == ["data_exported"]


def test_export_contains_only_your_own_data(client, db, member):
    make_user(db, email="other@example.com")
    sign_in(client, db, member)

    assert "other@example.com" not in client.get("/account/export").text


def test_deleting_your_account_removes_everything(client, db, member):
    db.add(Passkey(user_id=member.id, credential_id=b"phone", public_key=b"pk"))
    db.commit()
    other = make_user(db, email="other@example.com")
    sign_in(client, db, member)

    response = client.post("/account/delete", data={"confirm": "delete"}, follow_redirects=False)

    assert response.headers["location"] == "/login?notice=deleted"
    assert f'{SESSION_COOKIE}=""' in response.headers["set-cookie"]
    db.expire_all()
    assert [u.email for u in db.scalars(select(User))] == [other.email]
    assert count(db, Passkey) == 0
    assert count(db, UserSession) == 0
    # The security log keeps the event, without saying who it was.
    assert [(e.event, e.user_id) for e in db.scalars(select(AuditEvent))] == [
        ("account_deleted", None)
    ]
    assert (
        "Your account and all of its data have been deleted"
        in client.get("/login?notice=deleted").text
    )


def test_deleting_needs_the_word_delete(client, db, member):
    sign_in(client, db, member)

    response = client.post("/account/delete", data={"confirm": "yes"}, follow_redirects=False)

    assert response.headers["location"] == "/account"
    assert count(db, User) == 1


def test_the_only_admin_cannot_delete_their_account(client, db, admin):
    sign_in(client, db, admin)

    assert "can't be deleted until someone else is an admin" in client.get("/account").text
    response = client.post("/account/delete", data={"confirm": "DELETE"}, follow_redirects=False)

    assert response.headers["location"] == "/account?notice=only-admin"
    assert count(db, User) == 1


def test_delete_rejects_other_sites(client, db, member):
    sign_in(client, db, member)

    response = client.post(
        "/account/delete", data={"confirm": "DELETE"}, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403
    assert count(db, User) == 1


def test_more_links_to_your_data(client, db, member):
    sign_in(client, db, member)

    assert 'href="/account"' in client.get("/more").text
