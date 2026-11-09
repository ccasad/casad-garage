"""The Service, Due and To do tabs for the selected car."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app import cars
from app.sessions import DbSession, SignedInUser
from app.web import render

router = APIRouter()


def tab_page(
    request: Request, db: DbSession, user: SignedInUser, *, key: str, title: str, template: str
) -> HTMLResponse:
    car = cars.selected_car(db, user)
    return render(request, template, title=title, user=user, active=key, db=db, car=car)


@router.get("/todo", response_class=HTMLResponse)
def todo(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    return tab_page(request, db, user, key="todo", title="To do", template="pages/todo.html")
