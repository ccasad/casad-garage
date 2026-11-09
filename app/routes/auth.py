"""Passkey (WebAuthn) setup from an invite, passkey sign-in, and sign-out."""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, options_to_json_dict
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app import audit
from app.config import get_settings
from app.invites import find_pending_invite
from app.models import AuthChallenge, Invite, Passkey, User, utcnow
from app.sessions import CurrentUser, DbSession, end_session, same_origin, start_session
from app.theme import remember_theme
from app.web import render

router = APIRouter()

CHALLENGE_LIFETIME = timedelta(minutes=5)
INVALID_INVITE = "This invite link is invalid, used or expired. Ask for a new one."
TRY_AGAIN = "That didn't work. Please try again."


class RegisterOptionsIn(BaseModel):
    invite_token: str


class CredentialIn(BaseModel):
    challenge_id: uuid.UUID
    credential: dict[str, Any]


def error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def save_challenge(db: Session, purpose: str, challenge: bytes, **fields: Any) -> AuthChallenge:
    now = utcnow()
    # Clear out challenges from abandoned attempts while we're here.
    db.execute(delete(AuthChallenge).where(AuthChallenge.expires_at < now))
    record = AuthChallenge(
        purpose=purpose, challenge=challenge, expires_at=now + CHALLENGE_LIFETIME, **fields
    )
    db.add(record)
    db.commit()
    return record


def pop_challenge(db: Session, challenge_id: uuid.UUID, purpose: str) -> AuthChallenge | None:
    """Fetch and delete a challenge in one step, so each can be used only once."""
    record = db.get(AuthChallenge, challenge_id)
    if record is None or record.purpose != purpose:
        return None
    db.delete(record)
    db.commit()
    return record if utcnow() < record.expires_at else None


def signed_in_response(db: Session, user: User) -> JSONResponse:
    response = JSONResponse({"redirect": "/"})
    start_session(db, response, user)
    # This device now uses the account's appearance, even after signing out.
    remember_theme(response, user.theme)
    return response


LOGIN_NOTICES = {"deleted": "Your account and all of its data have been deleted."}


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: CurrentUser, notice: str | None = None) -> Response:
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return render(
        request,
        "pages/login.html",
        title="Sign in",
        user=None,
        notice=LOGIN_NOTICES.get(notice or ""),
    )


@router.get("/invite", response_class=HTMLResponse)
def invite_page(request: Request) -> HTMLResponse:
    # The invite token is in the URL fragment; passkeys.js reads it in the browser.
    return render(request, "pages/invite.html", title="Set up your passkey", user=None)


@router.post("/auth/register/options", dependencies=[Depends(same_origin)])
def register_options(body: RegisterOptionsIn, db: DbSession) -> JSONResponse:
    invite = find_pending_invite(db, body.invite_token)
    if invite is None:
        return error(INVALID_INVITE)

    # An invite for an existing email adds a passkey to that account (e.g. a new phone).
    existing = db.scalar(select(User).where(User.email == invite.email))
    user_handle = existing.id.bytes if existing else uuid.uuid4().bytes
    settings = get_settings()
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name=settings.app_name,
        user_name=invite.email,
        user_id=user_handle,
        user_display_name=invite.display_name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=passkey.credential_id)
            for passkey in (existing.passkeys if existing else [])
        ],
    )
    challenge = save_challenge(
        db, "register", options.challenge, invite_id=invite.id, user_handle=user_handle
    )
    return JSONResponse(
        {
            "challenge_id": str(challenge.id),
            "display_name": invite.display_name,
            "options": options_to_json_dict(options),
        }
    )


@router.post("/auth/register/verify", dependencies=[Depends(same_origin)])
def register_verify(body: CredentialIn, db: DbSession) -> JSONResponse:
    challenge = pop_challenge(db, body.challenge_id, "register")
    invite = db.get(Invite, challenge.invite_id) if challenge and challenge.invite_id else None
    if challenge is None or challenge.user_handle is None or invite is None:
        return error(TRY_AGAIN)
    if not invite.is_pending(utcnow()):
        return error(INVALID_INVITE)

    settings = get_settings()
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge.challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.origin,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        audit.record(
            db, "passkey_setup_failed", invite_id=str(invite.id), reason=type(exc).__name__
        )
        db.commit()
        return error(TRY_AGAIN)

    user = db.scalar(select(User).where(User.email == invite.email))
    if user is None:
        user = User(
            id=uuid.UUID(bytes=challenge.user_handle),
            email=invite.email,
            display_name=invite.display_name,
            role=invite.role,
        )
        db.add(user)
        db.flush()
    transports = body.credential.get("response", {}).get("transports") or []
    db.add(
        Passkey(
            user_id=user.id,
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=[str(t) for t in transports],
            backed_up=verified.credential_backed_up,
        )
    )
    audit.record(db, "passkey_registered", user_id=user.id, invite_id=str(invite.id))
    # A used invite has done its job; don't keep the name and email around.
    db.delete(invite)
    audit.record(db, "sign_in", user_id=user.id, method="passkey_setup")
    response = signed_in_response(db, user)
    db.commit()
    return response


@router.post("/auth/login/options", dependencies=[Depends(same_origin)])
def login_options(db: DbSession) -> JSONResponse:
    # No allow-list: the browser offers whichever of this site's passkeys it holds.
    options = generate_authentication_options(
        rp_id=get_settings().webauthn_rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    challenge = save_challenge(db, "authenticate", options.challenge)
    return JSONResponse(
        {"challenge_id": str(challenge.id), "options": options_to_json_dict(options)}
    )


@router.post("/auth/login/verify", dependencies=[Depends(same_origin)])
def login_verify(body: CredentialIn, db: DbSession) -> JSONResponse:
    challenge = pop_challenge(db, body.challenge_id, "authenticate")
    if challenge is None:
        return error(TRY_AGAIN)

    try:
        credential_id = base64url_to_bytes(str(body.credential.get("rawId", "")))
    except ValueError:
        return error(TRY_AGAIN)
    passkey = db.scalar(select(Passkey).where(Passkey.credential_id == credential_id))
    if passkey is None:
        audit.record(db, "sign_in_failed", reason="unknown_passkey")
        db.commit()
        return error("This passkey isn't set up for this app. Ask for an invite link.")

    settings = get_settings()
    try:
        verified = verify_authentication_response(
            credential=body.credential,
            expected_challenge=challenge.challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.origin,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        audit.record(db, "sign_in_failed", user_id=passkey.user_id, reason=type(exc).__name__)
        db.commit()
        return error(TRY_AGAIN)

    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = utcnow()
    audit.record(db, "sign_in", user_id=passkey.user_id, method="passkey")
    response = signed_in_response(db, passkey.user)
    db.commit()
    return response


@router.post("/logout", dependencies=[Depends(same_origin)])
def logout(request: Request, db: DbSession) -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    end_session(db, request, response)
    return response
