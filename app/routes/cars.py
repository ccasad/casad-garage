"""Cars: add, edit, delete, the car selector and the All cars view (FR-1, FR-3 to FR-6)."""

import re
import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app import audit, cars, documents, nhtsa, storage
from app.crypto import blind_index
from app.forms import cents_text, parse_cents, parse_date
from app.models import Car, Document, User, utcnow
from app.sessions import DbSession, SignedInUser, same_origin
from app.web import render, render_partial

router = APIRouter()

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def loan_fields(car: Car) -> dict[str, str]:
    loan = car.loan or {}
    return {
        "lender": loan.get("lender", ""),
        "loan_end": loan.get("final_date", ""),
        "loan_monthly": cents_text(loan.get("monthly_cents")),
    }


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
    visibility: str = "shared"
    lender: str = ""
    loan_end: str = ""
    loan_monthly: str = ""
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
            visibility=car.visibility,
            **loan_fields(car),
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
        self.lender = self.lender.strip()
        if any((self.lender, self.loan_end.strip(), self.loan_monthly.strip())):
            if not self.lender:
                self.errors["lender"] = "Enter the lender."
            elif len(self.lender) > 100:
                self.errors["lender"] = "Keep this under 100 characters."
            try:
                if not self.loan_end.strip():
                    raise ValueError("Enter the final payment date.")
                parse_date(self.loan_end)
            except ValueError as exc:
                self.errors["loan_end"] = str(exc)
            try:
                parse_cents(self.loan_monthly)
            except ValueError as exc:
                self.errors["loan_monthly"] = str(exc)
        if self.visibility not in ("shared", "private"):
            self.visibility = "shared"
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
        car.loan = (
            {
                "lender": self.lender,
                "final_date": self.loan_end.strip(),
                "monthly_cents": parse_cents(self.loan_monthly),
            }
            if self.lender
            else None
        )
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
    visibility: Annotated[str, Form(max_length=10)] = "shared",
    lender: Annotated[str, Form(max_length=300)] = "",
    loan_end: Annotated[str, Form(max_length=20)] = "",
    loan_monthly: Annotated[str, Form(max_length=30)] = "",
) -> CarForm:
    form = CarForm(
        year,
        make,
        model,
        nickname,
        vin,
        trim,
        engine,
        color,
        plate,
        notes,
        visibility,
        lender,
        loan_end,
        loan_monthly,
    )
    form.clean()
    return form


SubmittedCar = Annotated[CarForm, Depends(form_dependency)]


def car_form_page(
    request: Request,
    db: DbSession,
    user: User,
    form: CarForm,
    car: Car | None,
    invoice_id: str = "",
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
        invoice_id=invoice_id,
        can_set_visibility=car is None or car.added_by_id == user.id,
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
        sorts=cars.SORTS,
        sort=cars.get_prefs(db, user).car_sort,
        cards=cars.card_context(db, cars.ordered_cars(db, user)),
    )


def pending_invoice(db: DbSession, user: User, invoice_id: str) -> Document | None:
    """An uploaded invoice of this user's that still needs a car."""
    try:
        doc = documents.get_document(db, user, uuid.UUID(invoice_id), missing_ok=True)
    except ValueError:
        return None
    if doc is None or doc.car_id is not None or doc.status != "review" or not doc.parsed:
        return None
    return doc


@router.get("/cars/new", response_class=HTMLResponse)
def new_car_form(
    request: Request, db: DbSession, user: SignedInUser, invoice: str = ""
) -> HTMLResponse:
    form = CarForm()
    doc = pending_invoice(db, user, invoice) if invoice else None
    if doc:
        parsed = doc.parsed
        form = CarForm(
            year=parsed.get("year", ""),
            make=parsed.get("make", ""),
            model=parsed.get("model", ""),
            trim=parsed.get("trim", ""),
            vin=parsed.get("vin", ""),
        )
    return car_form_page(request, db, user, form, None, invoice_id=str(doc.id) if doc else "")


@router.post("/cars", dependencies=[Depends(same_origin)])
def create_car(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    form: SubmittedCar,
    invoice: Annotated[str, Form(max_length=40)] = "",
) -> Response:
    if form.errors:
        return car_form_page(request, db, user, form, None, invoice_id=invoice)
    car = Car(added_by_id=user.id, year=0, make="", model="", visibility=form.visibility)
    form.apply(car)
    db.add(car)
    db.flush()
    cars.sync_loan_due(db, car)
    cars.select_car(db, user, car)
    audit.record(db, "car_added", user_id=user.id, car_id=str(car.id), visibility=car.visibility)
    # A car added from an uploaded invoice takes the invoice, and the review continues.
    doc = pending_invoice(db, user, invoice) if invoice else None
    if doc:
        doc.car_id = car.id
    db.commit()
    return RedirectResponse(f"/invoices/{doc.id}/review" if doc else "/", status_code=303)


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
    cars.sync_loan_due(db, car)
    # Only the person who added a car can change who sees it (FR-8).
    if car.added_by_id == user.id and form.visibility != car.visibility:
        car.visibility = form.visibility
        audit.record(
            db, "car_visibility_changed", user_id=user.id, car_id=str(car.id), to=car.visibility
        )
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


MAX_PHOTO_BYTES = 3 * 1024 * 1024


@router.post("/cars/{car_id}/photo", dependencies=[Depends(same_origin)])
async def upload_photo(
    db: DbSession, user: SignedInUser, car_id: uuid.UUID, photo: Annotated[UploadFile, File()]
) -> Response:
    """The browser resizes the photo to a JPEG first (FR-7); this only checks and stores it."""
    car = cars.get_car(db, user, car_id)
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="The photo is too large.")
    if not data.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=415, detail="The photo must be a JPEG.")
    try:
        new_ref = storage.save("photos", "jpg", data, "image/jpeg")
    except storage.StorageError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    storage.remove(car.photo_ref)
    car.photo_ref = new_ref
    car.photo_updated_at = utcnow()
    db.commit()
    return Response(status_code=204)


@router.get("/cars/{car_id}/photo")
def photo(db: DbSession, user: SignedInUser, car_id: uuid.UUID) -> Response:
    car = cars.get_car(db, user, car_id)
    if not car.photo_ref:
        raise HTTPException(status_code=404, detail="No photo")
    try:
        data = storage.load(car.photo_ref)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail="No photo") from exc
    return Response(
        data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.post("/cars/vin-lookup", response_class=HTMLResponse, dependencies=[Depends(same_origin)])
def vin_lookup(
    request: Request,
    user: SignedInUser,
    vin: Annotated[str, Form(max_length=60)] = "",
    year: Annotated[str, Form(max_length=10)] = "",
    make: Annotated[str, Form(max_length=200)] = "",
    model: Annotated[str, Form(max_length=200)] = "",
    nickname: Annotated[str, Form(max_length=200)] = "",
    trim: Annotated[str, Form(max_length=200)] = "",
    engine: Annotated[str, Form(max_length=200)] = "",
    color: Annotated[str, Form(max_length=100)] = "",
    plate: Annotated[str, Form(max_length=100)] = "",
) -> HTMLResponse:
    """Fill the car form's fields from the VIN. Whatever it can't fill stays as typed."""
    form = CarForm(year, make, model, nickname, re.sub(r"\s+", "", vin).upper(), trim, engine)
    form.color, form.plate = color, plate
    message, ok = "", False
    if not VIN_RE.match(form.vin):
        message = "Enter the 17-character VIN first (no I, O or Q)."
    else:
        try:
            decoded = nhtsa.decode_vin(form.vin)
        except nhtsa.NhtsaError as exc:
            message = f"{exc} Type the details in instead."
        else:
            for name in ("year", "make", "model", "trim", "engine"):
                value = getattr(decoded, name)
                if value:
                    setattr(form, name, value)
            message, ok = "Filled in from the VIN. Check the details and correct anything.", True
    return render_partial(
        request, "partials/car_fields.html", form=form, lookup_message=message, lookup_ok=ok
    )


@router.post("/cars/{car_id}/star", dependencies=[Depends(same_origin)])
def star(
    db: DbSession,
    user: SignedInUser,
    car_id: uuid.UUID,
    next: Annotated[str, Form(max_length=40)] = "/cars",
) -> RedirectResponse:
    car = cars.get_car(db, user, car_id)
    cars.toggle_star(db, user, car)
    db.commit()
    return RedirectResponse(next if next in cars.TAB_PATHS else "/cars", status_code=303)


@router.post("/settings/car-sort", dependencies=[Depends(same_origin)])
def set_sort(
    db: DbSession,
    user: SignedInUser,
    sort: Annotated[str, Form(max_length=10)] = "name",
    next: Annotated[str, Form(max_length=40)] = "/cars",
) -> RedirectResponse:
    if sort not in dict(cars.SORTS):
        raise HTTPException(status_code=422, detail="Unknown sort")
    cars.get_prefs(db, user).car_sort = sort
    db.commit()
    return RedirectResponse(next if next in cars.TAB_PATHS else "/cars", status_code=303)
