"""Mileage readings: add on a car, history under More, edit and delete (FR-10)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select

from app import cars
from app.forms import parse_date, parse_miles
from app.models import Car, MileageReading
from app.sessions import DbSession, SignedInUser, same_origin
from app.web import render

router = APIRouter()


def get_reading(db: DbSession, user: SignedInUser, reading_id: uuid.UUID) -> MileageReading:
    """The reading, or 404 when its car isn't visible to the user."""
    reading = db.scalar(
        select(MileageReading)
        .join(Car, Car.id == MileageReading.car_id)
        .where(MileageReading.id == reading_id, cars.visible_filter(user))
    )
    if reading is None:
        raise HTTPException(status_code=404, detail="Reading not found")
    return reading


def history_page(
    request: Request, db: DbSession, user: SignedInUser, *, errors=None, values=None, status=200
) -> HTMLResponse:
    car = cars.selected_car(db, user)
    readings = []
    if car:
        readings = db.scalars(
            select(MileageReading)
            .where(MileageReading.car_id == car.id)
            .order_by(MileageReading.on.desc(), MileageReading.created_at.desc())
        ).all()
    return render(
        request,
        "pages/mileage.html",
        title="Mileage history",
        user=user,
        active="more",
        db=db,
        car=car,
        readings=readings,
        errors=errors or {},
        values=values or {},
        status_code=status,
    )


def clean_reading(on: str, miles: str) -> tuple[dict, dict]:
    errors, values = {}, {}
    for key, parser, text in (("on", parse_date, on), ("miles", parse_miles, miles)):
        try:
            values[key] = parser(text)
        except ValueError as exc:
            errors[key] = str(exc)
    return values, errors


@router.get("/mileage", response_class=HTMLResponse)
def mileage_history(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    return history_page(request, db, user)


@router.post("/cars/{car_id}/mileage", dependencies=[Depends(same_origin)])
def add_reading(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    car_id: uuid.UUID,
    on: Annotated[str, Form(max_length=20)] = "",
    miles: Annotated[str, Form(max_length=20)] = "",
    next: Annotated[str, Form(max_length=40)] = "/mileage",
) -> Response:
    car = cars.get_car(db, user, car_id)
    values, errors = clean_reading(on, miles)
    if errors:
        cars.select_car(db, user, car)
        db.commit()
        return history_page(
            request, db, user, errors=errors, values={"on": on, "miles": miles}, status=422
        )
    db.add(MileageReading(car_id=car.id, on=values["on"], miles=values["miles"]))
    db.commit()
    return RedirectResponse(next if next in cars.TAB_PATHS else "/mileage", status_code=303)


@router.get("/mileage/{reading_id}/edit", response_class=HTMLResponse)
def edit_form(
    request: Request, db: DbSession, user: SignedInUser, reading_id: uuid.UUID
) -> HTMLResponse:
    reading = get_reading(db, user, reading_id)
    return render(
        request,
        "pages/mileage_edit.html",
        title="Edit reading",
        user=user,
        active="more",
        db=db,
        reading=reading,
        errors={},
        values={"on": reading.on.isoformat(), "miles": str(reading.miles)},
    )


@router.post("/mileage/{reading_id}/edit", dependencies=[Depends(same_origin)])
def edit_reading(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    reading_id: uuid.UUID,
    on: Annotated[str, Form(max_length=20)] = "",
    miles: Annotated[str, Form(max_length=20)] = "",
) -> Response:
    reading = get_reading(db, user, reading_id)
    values, errors = clean_reading(on, miles)
    if errors:
        return render(
            request,
            "pages/mileage_edit.html",
            title="Edit reading",
            user=user,
            active="more",
            db=db,
            reading=reading,
            errors=errors,
            values={"on": on, "miles": miles},
            status_code=422,
        )
    reading.on, reading.miles = values["on"], values["miles"]
    db.commit()
    return RedirectResponse("/mileage", status_code=303)


@router.post("/mileage/{reading_id}/delete", dependencies=[Depends(same_origin)])
def delete_reading(db: DbSession, user: SignedInUser, reading_id: uuid.UUID) -> RedirectResponse:
    reading = get_reading(db, user, reading_id)
    db.delete(reading)
    db.commit()
    return RedirectResponse("/mileage", status_code=303)
