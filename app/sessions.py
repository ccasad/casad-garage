"""Server-side sessions: the cookie holds a random token, the database holds its hash."""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.db import get_db
from app.models import User, UserSession, utcnow
from app.security import hash_token, new_token

SESSION_COOKIE = "session"
ABSOLUTE_LIFETIME = timedelta(hours=12)
# Avoid a database write on every request; idle time is measured to the minute.
TOUCH_INTERVAL = timedelta(minutes=1)


class LoginRequired(Exception):
    """Raised by require_user; main.py turns it into a redirect to /login."""


def start_session(db: Session, response: Response, user: User) -> None:
    token = new_token()
    now = utcnow()
    # Sessions abandoned without signing out are otherwise never deleted.
    idle_cutoff = now - timedelta(minutes=get_settings().session_idle_minutes)
    db.execute(
        delete(UserSession).where(
            (UserSession.expires_at < now) | (UserSession.last_seen_at < idle_cutoff)
        )
    )
    user.last_active_at = now
    db.add(
        UserSession(
            token_hash=hash_token(token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + ABSOLUTE_LIFETIME,
        )
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="lax",
        path="/",
    )


def end_session(db: Session, request: Request, response: Response) -> None:
    session = load_session(db, request)
    if session is not None:
        audit.record(db, "sign_out", user_id=session.user_id)
        db.delete(session)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


def load_session(db: Session, request: Request) -> UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if session is None:
        return None

    now = utcnow()
    idle_limit = timedelta(minutes=get_settings().session_idle_minutes)
    if now - session.last_seen_at > idle_limit or now >= session.expires_at:
        db.delete(session)
        db.commit()
        return None
    if now - session.last_seen_at > TOUCH_INTERVAL:
        session.last_seen_at = now
        session.user.last_active_at = now  # same write, same minute granularity
        db.commit()
    return session


DbSession = Annotated[Session, Depends(get_db)]


def current_user(request: Request, db: DbSession) -> User | None:
    session = load_session(db, request)
    return session.user if session else None


def require_user(user: Annotated[User | None, Depends(current_user)]) -> User:
    if user is None:
        raise LoginRequired
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403)
    return user


def same_origin(request: Request) -> None:
    """Reject state-changing requests sent from another site (CSRF)."""
    if request.headers.get("origin") != get_settings().origin:
        raise HTTPException(status_code=403, detail="Cross-origin request blocked")


CurrentUser = Annotated[User | None, Depends(current_user)]
SignedInUser = Annotated[User, Depends(require_user)]
AdminUser = Annotated[User, Depends(require_admin)]
