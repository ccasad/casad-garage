"""The Service tab: history, filter and search, and logging, editing and deleting records
(FR-12, FR-13)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import cars, service
from app.models import Car, ServiceRecord
from app.service_types import SERVICE_TYPE_LABELS, SERVICE_TYPES
from app.sessions import DbSession, SignedInUser, same_origin
from app.web import render

router = APIRouter()


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
) -> HTMLResponse:
    return render(
        request,
        "pages/service_form.html",
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


async def read_form(request: Request) -> service.ServiceForm:
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
        items=service.build_items(
            lists("item_id"),
            lists("item_description"),
            lists("item_type"),
            lists("item_part"),
            lists("item_cost"),
        ),
    )
    return form.clean()


@router.get("/service", response_class=HTMLResponse, name="service")
def service_tab(
    request: Request,
    db: DbSession,
    user: SignedInUser,
    type: str = "",
    q: str = "",
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
    )


@router.get("/service/new", response_class=HTMLResponse)
def new_form(request: Request, db: DbSession, user: SignedInUser) -> Response:
    car = cars.selected_car(db, user)
    if car is None:
        return RedirectResponse("/service", status_code=303)
    return form_page(request, db, user, car, service.ServiceForm())


@router.post("/cars/{car_id}/service", dependencies=[Depends(same_origin)])
async def create(
    request: Request, db: DbSession, user: SignedInUser, car_id: uuid.UUID
) -> Response:
    car = cars.get_car(db, user, car_id)
    form = await read_form(request)
    if form.errors:
        return form_page(request, db, user, car, form)
    record = service.save_record(db, car, form)
    db.commit()
    return RedirectResponse(f"/service/{record.id}?saved=1", status_code=303)


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
