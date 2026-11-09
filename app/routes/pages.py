"""Signed-in pages: More, plus the theme setting."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.sessions import DbSession, SignedInUser, same_origin
from app.theme import THEMES, remember_theme
from app.web import render

router = APIRouter()


@router.get("/more", response_class=HTMLResponse, name="more")
def more(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    return render(request, "pages/more.html", title="More", user=user, active="more", db=db)


@router.post("/settings/theme", dependencies=[Depends(same_origin)])
def set_theme(
    db: DbSession,
    user: SignedInUser,
    theme: Annotated[str, Form(pattern=f"^({'|'.join(THEMES)})$")],
) -> RedirectResponse:
    user.theme = theme
    db.commit()
    response = RedirectResponse("/more", status_code=303)
    remember_theme(response, theme)
    return response
