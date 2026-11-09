"""Admin-only: invite people and remove accounts."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.invites import create_invite, invite_url, normalize_email, purge_spent_invites
from app.models import Invite, User
from app.sessions import AdminUser, DbSession, same_origin
from app.stats import sign_ins_by_user
from app.web import render

router = APIRouter(prefix="/admin")


def people_page(
    request: Request,
    db: Session,
    admin: User,
    *,
    new_link: str | None = None,
    form_error: str | None = None,
) -> HTMLResponse:
    purge_spent_invites(db)
    db.commit()
    users = db.scalars(select(User).order_by(User.created_at)).all()
    invites = db.scalars(select(Invite).order_by(Invite.created_at.desc())).all()
    return render(
        request,
        "pages/admin_people.html",
        title="People",
        user=admin,
        active="more",
        users=users,
        sign_ins=sign_ins_by_user(db),
        invites=invites,
        new_link=new_link,
        form_error=form_error,
        status_code=400 if form_error else 200,
    )


@router.get("/people", response_class=HTMLResponse)
def people(request: Request, db: DbSession, admin: AdminUser) -> HTMLResponse:
    return people_page(request, db, admin)


@router.post("/invites", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
def invite(
    request: Request,
    db: DbSession,
    admin: AdminUser,
    email: Annotated[str, Form(max_length=320)],
    display_name: Annotated[str, Form(max_length=100)],
) -> HTMLResponse:
    email = normalize_email(email)
    if "@" not in email or not display_name.strip():
        return people_page(request, db, admin, form_error="Enter a name and an email address.")
    token = create_invite(db, email=email, display_name=display_name, created_by=admin)
    db.commit()
    # The link is shown once; only its hash is stored.
    return people_page(request, db, admin, new_link=invite_url(token))


@router.post("/invites/{invite_id}/revoke", dependencies=[Depends(same_origin)])
def revoke_invite(invite_id: uuid.UUID, db: DbSession, admin: AdminUser) -> RedirectResponse:
    invite = db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status_code=404)
    audit.record(db, "invite_revoked", user_id=admin.id, invite_id=str(invite.id))
    db.delete(invite)
    db.commit()
    return RedirectResponse("/admin/people", status_code=303)


@router.post("/users/{user_id}/remove", dependencies=[Depends(same_origin)])
def remove_user(user_id: uuid.UUID, db: DbSession, admin: AdminUser) -> RedirectResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You can't remove your own account")
    # Deleting the user cascades to their passkeys and sessions.
    db.delete(user)
    audit.record(db, "user_removed", user_id=admin.id, removed_user_id=str(user_id))
    db.commit()
    return RedirectResponse("/admin/people", status_code=303)
