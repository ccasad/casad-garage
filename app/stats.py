"""Who uses the app: per-person activity for the admin, and counts for the factory.

Built only from what the app already keeps for sign-in: `users.last_active_at` and the
audit log's "sign_in" events. No page views, clicks or IP addresses are recorded.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Invite, User, utcnow

WINDOW = timedelta(days=30)


def sign_ins_by_user(db: Session) -> dict[uuid.UUID, int]:
    """Sign-ins in the last 30 days, per user."""
    rows = db.execute(
        select(AuditEvent.user_id, func.count())
        .where(AuditEvent.event == "sign_in", AuditEvent.at >= utcnow() - WINDOW)
        .group_by(AuditEvent.user_id)
    )
    return {user_id: count for user_id, count in rows if user_id is not None}


def summary(db: Session) -> dict[str, Any]:
    """Counts only, no names or emails: what the factory reports about this app."""
    now = utcnow()
    users = db.scalars(select(User)).all()
    active = [u.last_active_at for u in users if u.last_active_at]
    pending = db.scalar(
        select(func.count())
        .select_from(Invite)
        .where(Invite.used_at.is_(None), Invite.revoked_at.is_(None), Invite.expires_at > now)
    )
    return {
        "users": len(users),
        "admins": sum(1 for u in users if u.is_admin),
        "active_7d": sum(1 for t in active if t >= now - timedelta(days=7)),
        "active_30d": sum(1 for t in active if t >= now - WINDOW),
        "never_signed_in": sum(1 for u in users if u.last_active_at is None),
        "sign_ins_30d": sum(sign_ins_by_user(db).values()),
        "last_active": max(active).date().isoformat() if active else None,
        "pending_invites": pending,
    }
