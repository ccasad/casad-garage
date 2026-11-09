import json
import uuid
from datetime import timedelta

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app import cli
from app.models import AuditEvent, Invite, User, utcnow
from app.security import hash_token, new_token
from app.stats import summary
from tests.conftest import make_user, sign_in


def test_using_the_app_records_last_active(client, db, member):
    session = sign_in(client, db, member)
    session.last_seen_at = utcnow() - timedelta(minutes=5)  # due a touch, not idle yet
    db.commit()

    assert client.get("/").status_code == 200

    db.refresh(member)
    assert member.last_active_at is not None
    assert utcnow() - member.last_active_at < timedelta(minutes=1)


def add_sign_in(db, user, days_ago):
    db.add(AuditEvent(event="sign_in", user_id=user.id, at=utcnow() - timedelta(days=days_ago)))


def test_summary_counts_without_names(db, admin):
    now = utcnow()
    recent = make_user(db, email="recent@example.com", name="Recent")
    old = make_user(db, email="old@example.com", name="Old")
    make_user(db, email="never@example.com", name="Never")
    admin.last_active_at = now - timedelta(hours=1)
    recent.last_active_at = now - timedelta(days=3)
    old.last_active_at = now - timedelta(days=20)
    for user, days in [(admin, 0), (admin, 2), (recent, 3), (old, 20), (old, 45)]:
        add_sign_in(db, user, days)
    for used, revoked, expires in [
        (None, None, 1),
        (now, None, 1),
        (None, now, 1),
        (None, None, -1),
    ]:
        db.add(
            Invite(
                token_hash=hash_token(new_token()),
                email=f"{uuid.uuid4().hex}@example.com",
                display_name="Someone",
                expires_at=now + timedelta(days=expires),
                used_at=used,
                revoked_at=revoked,
            )
        )
    db.commit()

    stats = summary(db)

    assert stats == {
        "users": 4,
        "admins": 1,
        "active_7d": 2,
        "active_30d": 3,
        "never_signed_in": 1,
        "sign_ins_30d": 4,  # the one 45 days ago is outside the window
        "last_active": admin.last_active_at.date().isoformat(),
        "pending_invites": 1,  # not used, revoked or expired
    }
    assert "example.com" not in json.dumps(stats)


def test_admin_sees_each_persons_activity(client, db, admin):
    member = make_user(db)
    member.last_active_at = utcnow() - timedelta(days=2)
    add_sign_in(db, member, 2)
    add_sign_in(db, member, 1)
    make_user(db, email="new@example.com", name="Newcomer")
    db.commit()
    sign_in(client, db, admin)

    page = client.get("/admin/people").text

    assert "2 sign-ins in 30 days" in page
    assert "Hasn't signed in yet" in page


def test_members_cannot_see_activity(client, db, member):
    sign_in(client, db, member)

    assert client.get("/admin/people").status_code == 403


def test_stats_command_prints_json(engine, db, admin, monkeypatch, capsys):
    admin.last_active_at = utcnow()
    db.commit()
    monkeypatch.setattr(cli, "get_engine", lambda: engine)
    monkeypatch.setattr("sys.argv", ["app.cli", "stats"])

    cli.main()

    stats = json.loads(capsys.readouterr().out)
    assert stats["users"] == 1
    assert stats["active_7d"] == 1


def test_export_includes_last_active(client, db, member):
    sign_in(client, db, member)

    exported = client.get("/account/export").json()

    assert "last_active_at" in exported["account"]


def test_migration_backfills_last_active_from_sign_ins(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    config = Config("alembic.ini")
    user_id = uuid.uuid4().hex
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "cf2af9fbd324")
        connection.execute(
            text(
                "INSERT INTO users (id, email, display_name, role, theme, created_at)"
                " VALUES (:id, 'a@example.com', 'A', 'member', 'dark', '2026-01-01 00:00:00')"
            ),
            {"id": user_id},
        )
        for at in ("2026-02-01 10:00:00", "2026-03-05 09:30:00"):
            connection.execute(
                text(
                    "INSERT INTO audit_events (at, user_id, event, detail)"
                    " VALUES (:at, :id, 'sign_in', '{}')"
                ),
                {"at": at, "id": user_id},
            )
        command.upgrade(config, "head")
        backfilled = connection.execute(text("SELECT last_active_at FROM users")).scalar()

    assert str(backfilled).startswith("2026-03-05 09:30")
    assert User.__table__.c.last_active_at.nullable
