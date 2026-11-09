"""The Due tab: a car's due items, soonest first (FR-15 to FR-17)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app import cars, due, mileage
from app.forms import parse_date, parse_miles
from app.models import Car, DueItem, utcnow
from app.sessions import DbSession, SignedInUser, same_origin
from app.web import render

router = APIRouter()


def get_item(db: DbSession, user: SignedInUser, item_id: uuid.UUID) -> DueItem:
    item = db.scalar(
        select(DueItem)
        .join(Car, Car.id == DueItem.car_id)
        .where(DueItem.id == item_id, cars.visible_filter(user))
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Due item not found")
    return item


def clean(type_: str, due_date: str, due_miles: str, notes: str):
    errors: dict[str, str] = {}
    values: dict = {"notes": notes.strip() or None}
    if type_ not in due.DUE_TYPE_LABELS:
        errors["type"] = "Choose a type."
    values["type"] = type_
    for key, parser, text in (
        ("due_date", lambda t: parse_date(t, required=False), due_date),
        ("due_miles", lambda t: parse_miles(t, required=False), due_miles),
    ):
        try:
            values[key] = parser(text)
        except ValueError as exc:
            errors[key] = str(exc)
    if not errors and values["due_date"] is None and values["due_miles"] is None:
        errors["due_date"] = "Enter a due date, a due mileage, or both."
    if len(notes) > 2000:
        errors["notes"] = "Keep notes under 2000 characters."
    return values, errors


def form_page(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    car: Car,
    *,
    item=None,
    values=None,
    errors=None,
) -> HTMLResponse:
    errors = errors or {}
    return render(
        request,
        "pages/due_form.html",
        title="Edit due item" if item else "Add a due item",
        user=user,
        active="due",
        db=db,
        car=car,
        item=item,
        values=values or {},
        errors=errors,
        due_types=[t for t in due.DUE_TYPES if t[0] not in ("loan_payoff", "warranty_ends")]
        + ([t for t in due.DUE_TYPES if t[0] == (item.type if item else "")]),
        status_code=422 if errors else 200,
    )


@router.get("/due", response_class=HTMLResponse, name="due")
def due_tab(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    car = cars.selected_car(db, user)
    open_, done = [], []
    if car:
        reading = mileage.current_mileage(db, [car.id]).get(car.id)
        miles = reading.miles if reading else None
        items = list(db.scalars(select(DueItem).where(DueItem.car_id == car.id)))
        for item in sorted(items, key=due.sort_key):
            (done if item.done_at else open_).append((item, due.status(item, miles), miles))
        done.sort(key=lambda row: row[0].done_at, reverse=True)
    return render(
        request,
        "pages/due.html",
        title="Due",
        user=user,
        active="due",
        db=db,
        car=car,
        open_items=open_,
        done_items=done,
        type_labels=due.DUE_TYPE_LABELS,
        today=due.today(),
    )


@router.get("/due/new", response_class=HTMLResponse)
def new_form(request: Request, db: DbSession, user: SignedInUser) -> Response:
    car = cars.selected_car(db, user)
    if car is None:
        return RedirectResponse("/due", status_code=303)
    return form_page(request, db, user, car, values={"type": "registration"})


@router.post("/cars/{car_id}/due", dependencies=[Depends(same_origin)])
def create(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    car_id: uuid.UUID,
    type: Annotated[str, Form(max_length=30)] = "",
    due_date: Annotated[str, Form(max_length=20)] = "",
    due_miles: Annotated[str, Form(max_length=20)] = "",
    notes: Annotated[str, Form(max_length=4000)] = "",
) -> Response:
    car = cars.get_car(db, user, car_id)
    values, errors = clean(type, due_date, due_miles, notes)
    if errors:
        shown = {"type": type, "due_date": due_date, "due_miles": due_miles, "notes": notes}
        return form_page(request, db, user, car, values=shown, errors=errors)
    db.add(DueItem(car_id=car.id, **values))
    db.commit()
    return RedirectResponse("/due", status_code=303)


@router.get("/due/{item_id}/edit", response_class=HTMLResponse)
def edit_form(
    request: Request, db: DbSession, user: SignedInUser, item_id: uuid.UUID
) -> HTMLResponse:
    item = get_item(db, user, item_id)
    car = cars.get_car(db, user, item.car_id)
    values = {
        "type": item.type,
        "due_date": item.due_date.isoformat() if item.due_date else "",
        "due_miles": str(item.due_miles) if item.due_miles is not None else "",
        "notes": item.notes or "",
    }
    return form_page(request, db, user, car, item=item, values=values)


@router.post("/due/{item_id}/edit", dependencies=[Depends(same_origin)])
def update(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    item_id: uuid.UUID,
    type: Annotated[str, Form(max_length=30)] = "",
    due_date: Annotated[str, Form(max_length=20)] = "",
    due_miles: Annotated[str, Form(max_length=20)] = "",
    notes: Annotated[str, Form(max_length=4000)] = "",
) -> Response:
    item = get_item(db, user, item_id)
    car = cars.get_car(db, user, item.car_id)
    values, errors = clean(type, due_date, due_miles, notes)
    if item.source != "manual":
        errors["type"] = "This item follows the car's loan or warranty; change it there."
    if errors:
        shown = {"type": type, "due_date": due_date, "due_miles": due_miles, "notes": notes}
        return form_page(request, db, user, car, item=item, values=shown, errors=errors)
    for key, value in values.items():
        setattr(item, key, value)
    db.commit()
    return RedirectResponse("/due", status_code=303)


@router.post("/due/{item_id}/done", dependencies=[Depends(same_origin)])
def mark_done(db: DbSession, user: SignedInUser, item_id: uuid.UUID) -> RedirectResponse:
    item = get_item(db, user, item_id)
    item.done_at = item.done_at or utcnow()
    db.commit()
    return RedirectResponse("/due", status_code=303)


@router.post("/due/{item_id}/reopen", dependencies=[Depends(same_origin)])
def reopen(db: DbSession, user: SignedInUser, item_id: uuid.UUID) -> RedirectResponse:
    item = get_item(db, user, item_id)
    item.done_at = None
    db.commit()
    return RedirectResponse("/due", status_code=303)


@router.post("/due/{item_id}/delete", dependencies=[Depends(same_origin)])
def delete(db: DbSession, user: SignedInUser, item_id: uuid.UUID) -> RedirectResponse:
    item = get_item(db, user, item_id)
    if item.source == "manual":
        db.delete(item)
        db.commit()
    return RedirectResponse("/due", status_code=303)
