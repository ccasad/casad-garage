"""The Service tab: history, filter and search, and logging, editing and deleting records
(FR-12, FR-13)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import cars, documents, due, service
from app.forms import parse_date, parse_miles
from app.models import Car, Document, DueItem, ServiceRecord
from app.service_types import SERVICE_TYPE_LABELS, SERVICE_TYPES
from app.sessions import DbSession, SignedInUser, same_origin
from app.web import render

router = APIRouter()

# Why an uploaded invoice opened an empty record instead of the review screen (FR-22).
NOTICES = {
    "empty": "The PDF has no readable text (a scan or photo?). It's attached to this car; fill in the record by hand.",
    "layout": "This invoice layout isn't recognised. It's attached to this car; fill in the record by hand.",
    "unreadable": "That file couldn't be read as a PDF. It's attached to this car; fill in the record by hand.",
}


def get_record(db: DbSession, user: SignedInUser, record_id: uuid.UUID) -> ServiceRecord:
    """The record, or 404 when its car isn't visible to the user."""
    record = db.scalar(
        select(ServiceRecord)
        .join(Car, Car.id == ServiceRecord.car_id)
        .where(ServiceRecord.id == record_id, cars.visible_filter(user))
        .options(selectinload(ServiceRecord.items))
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


def form_page(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    car: Car,
    form: service.ServiceForm,
    record: ServiceRecord | None = None,
    notice: str = "",
) -> HTMLResponse:
    return render(
        request,
        "pages/service_form.html",
        notice=notice,
        title="Edit service" if record else "Log a service",
        user=user,
        active="service",
        db=db,
        car=car,
        form=form,
        record=record,
        service_types=SERVICE_TYPES,
        status_code=422 if form.errors else 200,
    )


async def read_form(request: Request, *, allow_no_items: bool = False) -> service.ServiceForm:
    data = await request.form()
    text = lambda key: str(data.get(key, ""))[:8000]
    lists = lambda key: [str(v)[:500] for v in data.getlist(key)][:60]
    form = service.ServiceForm(
        on=text("on"),
        miles=text("miles"),
        shop=text("shop"),
        ro_number=text("ro_number"),
        total=text("total"),
        notes=text("notes"),
        document_id=text("document_id")[:40],
        items=service.build_items(
            lists("item_id"),
            lists("item_description"),
            lists("item_type"),
            lists("item_part"),
            lists("item_cost"),
        ),
    )
    return form.clean(allow_no_items=allow_no_items)


@router.get("/service", response_class=HTMLResponse, name="service")
def service_tab(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    type: str = "",
    q: str = "",
    notice: str = "",
) -> HTMLResponse:
    car = cars.selected_car(db, user)
    records = service.records_for_car(db, car.id) if car else []
    shown = service.filter_records(records, type_=type, query=q)
    return render(
        request,
        "pages/service.html",
        title="Service",
        user=user,
        active="service",
        db=db,
        car=car,
        records=shown,
        total_records=len(records),
        service_types=SERVICE_TYPES,
        type_labels=SERVICE_TYPE_LABELS,
        filter_type=type,
        filter_q=q,
        notice=UPLOAD_NOTICES.get(notice, ""),
    )


@router.get("/service/new", response_class=HTMLResponse)
def new_form(
    request: Request, db: DbSession, user: SignedInUser, document: str = "", notice: str = ""
) -> Response:
    car = cars.selected_car(db, user)
    if car is None:
        return RedirectResponse("/service", status_code=303)
    form = service.ServiceForm()
    if attached_document(db, user, car, document):
        form.document_id = document
    return form_page(request, db, user, car, form, notice=NOTICES.get(notice, ""))


def attached_document(db, user, car: Car, document_id: str) -> Document | None:
    """The uploaded invoice named by the form, if it belongs to this car and the user can see it."""
    try:
        doc_id = uuid.UUID(document_id)
    except ValueError:
        return None
    doc = documents.get_document(db, user, doc_id, missing_ok=True)
    return doc if doc is not None and doc.car_id == car.id else None


@router.post("/cars/{car_id}/service", dependencies=[Depends(same_origin)])
async def create(
    request: Request, db: DbSession, user: SignedInUser, car_id: uuid.UUID
) -> Response:
    car = cars.get_car(db, user, car_id)
    form = await read_form(request)
    if form.errors:
        return form_page(request, db, user, car, form)
    doc = attached_document(db, user, car, form.document_id)
    record = service.save_record(db, car, form, document_id=doc.id if doc else None)
    # The work is done, so any open due item of the same kind is closed (FR-16).
    due.close_open(db, car.id, {i.type for i in record.items} & set(due.FOLLOW_UP_TYPES))
    db.commit()
    return RedirectResponse(f"/service/{record.id}?saved=1", status_code=303)


def offers(record: ServiceRecord) -> list[dict]:
    """Next-due suggestions for inspection and oil-change items (FR-16)."""
    out = []
    for type_ in due.FOLLOW_UP_TYPES:
        if any(i.type == type_ for i in record.items):
            months = 6 if type_ == "oil_change" else 12
            year, month = divmod(record.on.month - 1 + months, 12)
            day = min(record.on.day, 28)
            out.append(
                {
                    "type": type_,
                    "label": due.DUE_TYPE_LABELS[type_],
                    "date": record.on.replace(
                        year=record.on.year + year, month=month + 1, day=day
                    ).isoformat(),
                    "miles": str(record.miles + 5000)
                    if type_ == "oil_change" and record.miles
                    else "",
                }
            )
    return out


@router.get("/service/{record_id}", response_class=HTMLResponse)
def detail(
    request: Request, db: DbSession, user: SignedInUser, record_id: uuid.UUID, saved: str = ""
) -> HTMLResponse:
    record = get_record(db, user, record_id)
    car = cars.get_car(db, user, record.car_id)
    return render(
        request,
        "pages/service_detail.html",
        title="Service record",
        user=user,
        active="service",
        db=db,
        car=car,
        record=record,
        type_labels=SERVICE_TYPE_LABELS,
        saved=bool(saved),
        offers=offers(record) if saved else [],
        errors={},
    )


@router.get("/service/{record_id}/edit", response_class=HTMLResponse)
def edit_form(
    request: Request, db: DbSession, user: SignedInUser, record_id: uuid.UUID
) -> HTMLResponse:
    record = get_record(db, user, record_id)
    car = cars.get_car(db, user, record.car_id)
    return form_page(request, db, user, car, service.ServiceForm.from_record(record), record)


@router.post("/service/{record_id}/edit", dependencies=[Depends(same_origin)])
async def update(
    request: Request, db: DbSession, user: SignedInUser, record_id: uuid.UUID
) -> Response:
    record = get_record(db, user, record_id)
    car = cars.get_car(db, user, record.car_id)
    form = await read_form(request)
    if form.errors:
        return form_page(request, db, user, car, form, record)
    service.save_record(db, car, form, record)
    db.commit()
    return RedirectResponse(f"/service/{record.id}?saved=1", status_code=303)


@router.post("/service/{record_id}/delete", dependencies=[Depends(same_origin)])
def delete(db: DbSession, user: SignedInUser, record_id: uuid.UUID) -> RedirectResponse:
    record = get_record(db, user, record_id)
    db.delete(record)
    db.commit()
    return RedirectResponse("/service", status_code=303)


@router.post("/service/{record_id}/next-due", dependencies=[Depends(same_origin)])
def set_next_due(
    db: DbSession,
    user: SignedInUser,
    record_id: uuid.UUID,
    type: Annotated[str, Form(max_length=30)] = "",
    due_date: Annotated[str, Form(max_length=20)] = "",
    due_miles: Annotated[str, Form(max_length=20)] = "",
) -> RedirectResponse:
    """Set the next due date or mileage after an inspection or oil change (FR-16)."""
    record = get_record(db, user, record_id)
    if type not in due.FOLLOW_UP_TYPES or not any(i.type == type for i in record.items):
        raise HTTPException(status_code=422, detail="That service has no such item")
    try:
        new_date = parse_date(due_date, required=False)
        new_miles = parse_miles(due_miles, required=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if new_date is None and new_miles is None:
        raise HTTPException(status_code=422, detail="Enter a due date or a due mileage")
    due.close_open(db, record.car_id, [type])
    db.add(DueItem(car_id=record.car_id, type=type, due_date=new_date, due_miles=new_miles))
    db.commit()
    return RedirectResponse("/due", status_code=303)


UPLOAD_NOTICES = {
    "type": "That file isn't a PDF.",
    "size": "That PDF is larger than 10 MB.",
    "storage": "The file couldn't be saved. Try again.",
    "no-car": "Pick a car (top right) before uploading an invoice.",
}
