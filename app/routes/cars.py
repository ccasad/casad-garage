"""Cars: add, edit, delete, the car selector and the All cars view (FR-1, FR-3 to FR-6)."""

import re
import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import audit, cars
from app.crypto import blind_index
from app.models import Car, User
from app.sessions import DbSession, SignedInUser, same_origin
from app.web import render

router = APIRouter()

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


@dataclass
class CarForm:
    """What the add/edit form submitted, cleaned up, with a message per bad field."""

    year: str = ""
    make: str = ""
    model: str = ""
    nickname: str = ""
    vin: str = ""
    trim: str = ""
    engine: str = ""
    color: str = ""
    plate: str = ""
    notes: str = ""
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_car(cls, car: Car) -> "CarForm":
        return cls(
            year=str(car.year),
            make=car.make,
            model=car.model,
            nickname=car.nickname or "",
            vin=car.vin or "",
            trim=car.trim or "",
            engine=car.engine or "",
            color=car.color or "",
            plate=car.plate or "",
            notes=car.notes or "",
        )

    def clean(self) -> None:
        for name in ("make", "model", "nickname", "trim", "engine", "color", "plate", "notes"):
            setattr(self, name, getattr(self, name).strip())
        self.year = self.year.strip()
        self.vin = re.sub(r"\s+", "", self.vin).upper()
        if not (self.year.isdigit() and 1900 <= int(self.year) <= 2100):
            self.errors["year"] = "Enter a 4-digit year, like 2019."
        if not self.make:
            self.errors["make"] = "Make is required."
        if not self.model:
            self.errors["model"] = "Model is required."
        if self.vin and not VIN_RE.match(self.vin):
            self.errors["vin"] = "A VIN is 17 letters and numbers (no I, O or Q)."
        limits = {"make": 60, "model": 80, "nickname": 60, "trim": 80, "engine": 80, "color": 40}
        for name, limit in limits.items():
            if len(getattr(self, name)) > limit:
                self.errors[name] = f"Keep this under {limit} characters."
        if len(self.plate) > 20:
            self.errors["plate"] = "Keep this under 20 characters."
        if len(self.notes) > 4000:
            self.errors["notes"] = "Keep notes under 4000 characters."

    def apply(self, car: Car) -> None:
        car.year = int(self.year)
        car.make = self.make
        car.model = self.model
        car.nickname = self.nickname or None
        car.trim = self.trim or None
        car.engine = self.engine or None
        car.color = self.color or None
        car.plate = self.plate or None
        car.notes = self.notes or None
        car.vin = self.vin or None
        car.vin_hash = blind_index(self.vin) if self.vin else None


def form_dependency(
    year: Annotated[str, Form(max_length=10)] = "",
    make: Annotated[str, Form(max_length=200)] = "",
    model: Annotated[str, Form(max_length=200)] = "",
    nickname: Annotated[str, Form(max_length=200)] = "",
    vin: Annotated[str, Form(max_length=60)] = "",
    trim: Annotated[str, Form(max_length=200)] = "",
    engine: Annotated[str, Form(max_length=200)] = "",
    color: Annotated[str, Form(max_length=100)] = "",
    plate: Annotated[str, Form(max_length=100)] = "",
    notes: Annotated[str, Form(max_length=8000)] = "",
) -> CarForm:
    form = CarForm(year, make, model, nickname, vin, trim, engine, color, plate, notes)
    form.clean()
    return form


SubmittedCar = Annotated[CarForm, Depends(form_dependency)]


def car_form_page(
    request: Request, db: DbSession, user: User, form: CarForm, car: Car | None
) -> HTMLResponse:
    return render(
        request,
        "pages/car_form.html",
        title="Edit car" if car else "Add a car",
        user=user,
        active="overview",
        db=db,
        form=form,
        car=car,
        status_code=422 if form.errors else 200,
    )


@router.get("/", response_class=HTMLResponse, name="overview")
def overview(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    car = cars.selected_car(db, user)
    return render(
        request,
        "pages/overview.html",
        title="Overview",
        user=user,
        active="overview",
        db=db,
        car=car,
        **(cars.overview_context(db, car) if car else {}),
    )


@router.get("/cars", response_class=HTMLResponse, name="all_cars")
def all_cars(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    return render(
        request,
        "pages/cars_all.html",
        title="All cars",
        user=user,
        active="overview",
        db=db,
        cars=cars.ordered_cars(db, user),
        cards=cars.card_context(db, cars.ordered_cars(db, user)),
    )


@router.get("/cars/new", response_class=HTMLResponse)
def new_car_form(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    return car_form_page(request, db, user, CarForm(), None)


@router.post("/cars", dependencies=[Depends(same_origin)])
def create_car(request: Request, db: DbSession, user: SignedInUser, form: SubmittedCar) -> Response:
    if form.errors:
        return car_form_page(request, db, user, form, None)
    car = Car(added_by_id=user.id, year=0, make="", model="")
    form.apply(car)
    db.add(car)
    db.flush()
    cars.select_car(db, user, car)
    audit.record(db, "car_added", user_id=user.id, car_id=str(car.id))
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.get("/cars/{car_id}/edit", response_class=HTMLResponse)
def edit_car_form(
    request: Request, db: DbSession, user: SignedInUser, car_id: uuid.UUID
) -> HTMLResponse:
    car = cars.get_car(db, user, car_id)
    return car_form_page(request, db, user, CarForm.from_car(car), car)


@router.post("/cars/{car_id}/edit", dependencies=[Depends(same_origin)])
def update_car(
    request: Request, db: DbSession, user: SignedInUser, car_id: uuid.UUID, form: SubmittedCar
) -> Response:
    car = cars.get_car(db, user, car_id)
    if form.errors:
        return car_form_page(request, db, user, form, car)
    form.apply(car)
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/cars/{car_id}/select", dependencies=[Depends(same_origin)])
def select(
    db: DbSession,
    user: SignedInUser,
    car_id: uuid.UUID,
    next: Annotated[str, Form(max_length=40)] = "/",
) -> RedirectResponse:
    car = cars.get_car(db, user, car_id)
    cars.select_car(db, user, car)
    db.commit()
    return RedirectResponse(next if next in cars.TAB_PATHS else "/", status_code=303)


@router.post("/cars/{car_id}/delete", dependencies=[Depends(same_origin)])
def delete_car(db: DbSession, user: SignedInUser, car_id: uuid.UUID) -> RedirectResponse:
    car = cars.get_car(db, user, car_id)
    if not cars.can_delete(user, car):
        raise HTTPException(status_code=403, detail="Only the person who added a car can delete it")
    audit.record(db, "car_deleted", user_id=user.id, car_id=str(car.id))
    # Records, documents and the photo go with it (cascades; files are removed first).
    cars.delete_car_files(db, car)
    db.delete(car)
    db.commit()
    return RedirectResponse("/", status_code=303)
