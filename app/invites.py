from datetime import timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.models import Invite, User, utcnow
from app.security import hash_token, new_link_token

INVITE_LIFETIME = timedelta(days=7)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_invite(
    db: Session,
    *,
    email: str,
    display_name: str,
    role: str = "member",
    created_by: User | None = None,
) -> str:
    """Create an invite and return its token. Only the token's hash is stored."""
    purge_spent_invites(db)
    token = new_link_token()
    invite = Invite(
        token_hash=hash_token(token),
        email=normalize_email(email),
        display_name=display_name.strip(),
        role=role,
        created_by_id=created_by.id if created_by else None,
        expires_at=utcnow() + INVITE_LIFETIME,
    )
    db.add(invite)
    db.flush()
    audit.record(
        db,
        "invite_created",
        user_id=created_by.id if created_by else None,
        invite_id=str(invite.id),
        role=role,
    )
    return token


def invite_url(token: str) -> str:
    # The token goes in the fragment, which browsers never send to the server,
    # so it can't end up in request logs.
    return f"{get_settings().origin}/invite#{token}"


def find_pending_invite(db: Session, token: str) -> Invite | None:
    invite = db.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    if invite is None or not invite.is_pending(utcnow()):
        return None
    return invite


def purge_spent_invites(db: Session) -> None:
    """Expired, used or revoked invites only hold names and emails nobody needs."""
    db.execute(
        delete(Invite).where(
            or_(
                Invite.expires_at < utcnow(),
                Invite.used_at.is_not(None),
                Invite.revoked_at.is_not(None),
            )
        )
    )
