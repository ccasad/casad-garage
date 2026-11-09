"""The To do tab: work a shop recommended that hasn't been done yet (FR-24 to FR-26)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app import cars, due, mileage, service
from app.forms import cents_text, parse_cents, parse_date, parse_miles
from app.models import Car, RecommendedItem, ServiceRecord, utcnow
from app.sessions import DbSession, SignedInUser, same_origin
from app.web import render

router = APIRouter()


def get_item(db: DbSession, user: SignedInUser, item_id: uuid.UUID) -> RecommendedItem:
    item = db.scalar(
        select(RecommendedItem)
        .join(Car, Car.id == RecommendedItem.car_id)
        .where(RecommendedItem.id == item_id, cars.visible_filter(user))
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def clean(description: str, note: str, price: str, on: str, miles: str):
    errors: dict[str, str] = {}
    values: dict = {"description": description.strip(), "shop_note": note.strip() or None}
    if not values["description"]:
        errors["description"] = "Describe the work."
    elif len(values["description"]) > 200:
        errors["description"] = "Keep this under 200 characters."
    if len(note) > 2000:
        errors["note"] = "Keep the note under 2000 characters."
    for key, parser, text, field in (
        ("price_cents", parse_cents, price, "price"),
        ("recommended_on", lambda t: parse_date(t, required=False), on, "on"),
        ("recommended_miles", lambda t: parse_miles(t, required=False), miles, "miles"),
    ):
        try:
            values[key] = parser(text)
        except ValueError as exc:
            errors[field] = str(exc)
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
        "pages/todo_form.html",
        title="Edit recommended work" if item else "Add recommended work",
        user=user,
        active="todo",
        db=db,
        car=car,
        item=item,
        values=values or {},
        errors=errors,
        status_code=422 if errors else 200,
    )


@router.get("/todo", response_class=HTMLResponse, name="todo")
def todo_tab(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    car = cars.selected_car(db, user)
    open_items, closed, records = [], [], []
    if car:
        items = list(
            db.scalars(
                select(RecommendedItem)
                .where(RecommendedItem.car_id == car.id)
                .order_by(RecommendedItem.created_at, RecommendedItem.description)
            )
        )
        open_items = [i for i in items if i.status == "open"]
        closed = sorted(
            (i for i in items if i.status != "open"),
            key=lambda i: i.closed_at or i.created_at,
            reverse=True,
        )
        records = service.records_for_car(db, car.id)[:40]
    priced = [i.price_cents for i in open_items if i.price_cents is not None]
    return render(
        request,
        "pages/todo.html",
        title="To do",
        user=user,
        active="todo",
        db=db,
        car=car,
        open_items=open_items,
        closed_items=closed,
        records=records,
        total_cents=sum(priced),
        unpriced=len(open_items) - len(priced),
        record_by_id={r.id: r for r in records},
    )


@router.get("/todo/new", response_class=HTMLResponse)
def new_form(request: Request, db: DbSession, user: SignedInUser) -> Response:
    car = cars.selected_car(db, user)
    if car is None:
        return RedirectResponse("/todo", status_code=303)
    return form_page(request, db, user, car, values={"on": due.today().isoformat()})


@router.post("/cars/{car_id}/todo", dependencies=[Depends(same_origin)])
def create(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    car_id: uuid.UUID,
    description: Annotated[str, Form(max_length=400)] = "",
    note: Annotated[str, Form(max_length=4000)] = "",
    price: Annotated[str, Form(max_length=30)] = "",
    on: Annotated[str, Form(max_length=20)] = "",
    miles: Annotated[str, Form(max_length=20)] = "",
) -> Response:
    car = cars.get_car(db, user, car_id)
    values, errors = clean(description, note, price, on, miles)
    if errors:
        shown = {"description": description, "note": note, "price": price, "on": on, "miles": miles}
        return form_page(request, db, user, car, values=shown, errors=errors)
    if values["recommended_miles"] is None:
        reading = mileage.current_mileage(db, [car.id]).get(car.id)
        values["recommended_miles"] = reading.miles if reading else None
    db.add(RecommendedItem(car_id=car.id, **values))
    db.commit()
    return RedirectResponse("/todo", status_code=303)


@router.get("/todo/{item_id}/edit", response_class=HTMLResponse)
def edit_form(
    request: Request, db: DbSession, user: SignedInUser, item_id: uuid.UUID
) -> HTMLResponse:
    item = get_item(db, user, item_id)
    car = cars.get_car(db, user, item.car_id)
    values = {
        "description": item.description,
        "note": item.shop_note or "",
        "price": cents_text(item.price_cents),
        "on": item.recommended_on.isoformat() if item.recommended_on else "",
        "miles": str(item.recommended_miles) if item.recommended_miles is not None else "",
    }
    return form_page(request, db, user, car, item=item, values=values)


@router.post("/todo/{item_id}/edit", dependencies=[Depends(same_origin)])
def update(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    item_id: uuid.UUID,
    description: Annotated[str, Form(max_length=400)] = "",
    note: Annotated[str, Form(max_length=4000)] = "",
    price: Annotated[str, Form(max_length=30)] = "",
    on: Annotated[str, Form(max_length=20)] = "",
    miles: Annotated[str, Form(max_length=20)] = "",
) -> Response:
    item = get_item(db, user, item_id)
    car = cars.get_car(db, user, item.car_id)
    values, errors = clean(description, note, price, on, miles)
    if errors:
        shown = {"description": description, "note": note, "price": price, "on": on, "miles": miles}
        return form_page(request, db, user, car, item=item, values=shown, errors=errors)
    for key, value in values.items():
        setattr(item, key, value)
    db.commit()
    return RedirectResponse("/todo", status_code=303)


@router.post("/todo/{item_id}/done", dependencies=[Depends(same_origin)])
def mark_done(
    db: DbSession,
    user: SignedInUser,
    item_id: uuid.UUID,
    record_id: Annotated[str, Form(max_length=40)] = "",
) -> RedirectResponse:
    """Mark done, optionally linking the service record that did the work (FR-26)."""
    item = get_item(db, user, item_id)
    if record_id:
        try:
            record = db.scalar(
                select(ServiceRecord).where(
                    ServiceRecord.id == uuid.UUID(record_id), ServiceRecord.car_id == item.car_id
                )
            )
        except ValueError:
            record = None
        if record is None:
            raise HTTPException(status_code=422, detail="Choose a service record for this car")
        item.done_record_id = record.id
    item.status, item.closed_at = "done", utcnow()
    db.commit()
    return RedirectResponse("/todo", status_code=303)


@router.post("/todo/{item_id}/dismiss", dependencies=[Depends(same_origin)])
def dismiss(db: DbSession, user: SignedInUser, item_id: uuid.UUID) -> RedirectResponse:
    item = get_item(db, user, item_id)
    item.status, item.closed_at, item.done_record_id = "dismissed", utcnow(), None
    db.commit()
    return RedirectResponse("/todo", status_code=303)


@router.post("/todo/{item_id}/reopen", dependencies=[Depends(same_origin)])
def reopen(db: DbSession, user: SignedInUser, item_id: uuid.UUID) -> RedirectResponse:
    item = get_item(db, user, item_id)
    item.status, item.closed_at, item.done_record_id = "open", None, None
    db.commit()
    return RedirectResponse("/todo", status_code=303)
