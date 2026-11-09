"""Invoice PDFs: upload, read, review, save, and the Documents list (FR-18 to FR-24, FR-22)."""

import uuid
from dataclasses import dataclass
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select

from app import audit, cars, documents, due, invoice, service, storage
from app.crypto import blind_index
from app.forms import cents_text, parse_cents
from app.models import (
    Car,
    Document,
    MileageReading,
    RecommendedItem,
    ServiceRecord,
    User,
)
from app.routes.service import read_form
from app.service_types import SERVICE_TYPES
from app.sessions import DbSession, SignedInUser, same_origin
from app.web import render

router = APIRouter()


@dataclass
class DeclinedRow:
    description: str = ""
    note: str = ""
    price: str = ""


def clean_filename(name: str | None) -> str:
    base = PurePath((name or "").replace("\\", "/")).name.strip()
    return (base or "invoice.pdf")[:120]


def find_cars_by_vin(db: DbSession, user: User, vin: str) -> list[Car]:
    if not vin:
        return []
    return list(db.scalars(cars.visible_cars_query(user).where(Car.vin_hash == blind_index(vin))))


@router.post("/invoices", dependencies=[Depends(same_origin)])
async def upload(
    db: DbSession,
    user: SignedInUser,
    invoice_file: Annotated[UploadFile, File(alias="invoice")],
    car_id: Annotated[str, Form(max_length=40)] = "",
) -> RedirectResponse:
    selected = None
    if car_id:
        try:
            selected = cars.get_car(db, user, uuid.UUID(car_id))
        except ValueError:
            selected = None
    selected = selected or cars.selected_car(db, user)

    data = await invoice_file.read(invoice.MAX_PDF_BYTES + 1)
    if len(data) > invoice.MAX_PDF_BYTES:
        return RedirectResponse("/service?notice=size", status_code=303)
    if not data.startswith(b"%PDF-"):
        return RedirectResponse("/service?notice=type", status_code=303)

    parsed, problem = None, ""
    try:
        text = invoice.extract_text(data)
        if not text.strip():
            problem = "empty"
        else:
            parsed = invoice.parse_invoice(text)
            if parsed is None:
                problem = "layout"
    except invoice.InvoiceError:
        problem = "unreadable"

    if parsed is None and selected is None:
        return RedirectResponse("/service?notice=no-car", status_code=303)

    try:
        ref = storage.save("invoices", "pdf", data, "application/pdf")
    except storage.StorageError as exc:
        notice = "storage-setup" if exc.operation is None else "storage"
        return RedirectResponse(f"/service?notice={notice}", status_code=303)

    doc = Document(
        uploaded_by_id=user.id,
        filename=clean_filename(invoice_file.filename),
        storage_ref=ref,
        size_bytes=len(data),
    )
    db.add(doc)
    if parsed is None:
        # Keep the file with the car and let the user type the record in (FR-22).
        doc.car_id = selected.id
        db.flush()
        audit.record(db, "invoice_uploaded", user_id=user.id, document_id=str(doc.id), read=False)
        db.commit()
        return RedirectResponse(f"/service/new?document={doc.id}&notice={problem}", status_code=303)

    matches = find_cars_by_vin(db, user, parsed.vin)
    doc.car_id = matches[0].id if matches else None
    doc.status = "review"
    doc.parsed = parsed.to_json()
    db.flush()
    if matches:
        cars.select_car(db, user, matches[0])
    audit.record(db, "invoice_uploaded", user_id=user.id, document_id=str(doc.id), read=True)
    db.commit()
    return RedirectResponse(f"/invoices/{doc.id}/review", status_code=303)


def declined_rows(parsed: invoice.ParsedInvoice) -> list[DeclinedRow]:
    return [
        DeclinedRow(j.title, j.shop_note or j.note, cents_text(j.price_cents))
        for j in parsed.declined
    ]


def prefilled_form(doc: Document, parsed: invoice.ParsedInvoice) -> service.ServiceForm:
    notes = [f"{j.title}: {j.note}" for j in parsed.approved if j.note]
    return service.ServiceForm(
        on=parsed.on or "",
        miles=str(parsed.odometer) if parsed.odometer is not None else "",
        shop=parsed.shop,
        ro_number=parsed.ro_number,
        total=cents_text(parsed.grand_total_cents),
        notes="\n".join(notes),
        document_id=str(doc.id),
        items=[
            service.ItemInput(j.title, j.type, "", cents_text(j.price_cents))
            for j in parsed.approved
        ]
        or [service.ItemInput()],
    )


def find_duplicate(db: DbSession, user: User, shop: str, ro_number: str) -> ServiceRecord | None:
    """A record the user can see with the same shop and repair order number (FR-23)."""
    if not ro_number.strip():
        return None
    return db.scalar(
        select(ServiceRecord)
        .join(Car, Car.id == ServiceRecord.car_id)
        .where(
            cars.visible_filter(user),
            ServiceRecord.ro_number == ro_number.strip(),
            func.lower(func.coalesce(ServiceRecord.shop, "")) == shop.strip().lower(),
        )
        .limit(1)
    )


def review_page(
    request: Request,
    db: DbSession,
    user: User,
    doc: Document,
    form: service.ServiceForm,
    rows: list[DeclinedRow],
    *,
    row_errors: str = "",
    duplicate: ServiceRecord | None = None,
) -> HTMLResponse:
    car = cars.get_car(db, user, doc.car_id) if doc.car_id else None
    return render(
        request,
        "pages/invoice_review.html",
        title="Review invoice",
        user=user,
        active="service",
        db=db,
        car=car,
        doc=doc,
        form=form,
        rows=rows or [DeclinedRow()],
        row_errors=row_errors,
        duplicate=duplicate,
        service_types=SERVICE_TYPES,
        choices=cars.ordered_cars(db, user) if car is None else [],
        status_code=422 if form.errors or row_errors else 200,
    )


def get_pending(
    db: DbSession, user: User, doc_id: uuid.UUID
) -> tuple[Document, invoice.ParsedInvoice]:
    doc = documents.get_document(db, user, doc_id)
    if doc.status != "review" or not doc.parsed:
        raise HTTPException(status_code=404, detail="Nothing to review")
    return doc, invoice.ParsedInvoice.from_json(doc.parsed)


@router.get("/invoices/{doc_id}/review", response_class=HTMLResponse)
def review(request: Request, db: DbSession, user: SignedInUser, doc_id: uuid.UUID) -> HTMLResponse:
    doc, parsed = get_pending(db, user, doc_id)
    form = prefilled_form(doc, parsed)
    duplicate = find_duplicate(db, user, form.shop, form.ro_number) if doc.car_id else None
    return review_page(request, db, user, doc, form, declined_rows(parsed), duplicate=duplicate)


@router.post("/invoices/{doc_id}/car", dependencies=[Depends(same_origin)])
def choose_car(
    db: DbSession,
    user: SignedInUser,
    doc_id: uuid.UUID,
    car_id: Annotated[str, Form(max_length=40)] = "",
) -> RedirectResponse:
    doc, _ = get_pending(db, user, doc_id)
    try:
        car = cars.get_car(db, user, uuid.UUID(car_id))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Choose a car") from exc
    doc.car_id = car.id
    cars.select_car(db, user, car)
    db.commit()
    return RedirectResponse(f"/invoices/{doc.id}/review", status_code=303)


def read_declined(data) -> tuple[list[DeclinedRow], list[tuple[str, str, int | None]], str]:
    """The declined-job rows the browser submitted: (shown rows, clean rows, error)."""
    descriptions = [str(v)[:300] for v in data.getlist("rec_description")][:60]
    notes = [str(v)[:1000] for v in data.getlist("rec_note")][:60]
    prices = [str(v)[:30] for v in data.getlist("rec_price")][:60]
    shown, clean, error = [], [], ""
    for i, description in enumerate(descriptions):
        row = DeclinedRow(
            description, notes[i] if i < len(notes) else "", prices[i] if i < len(prices) else ""
        )
        if not (row.description.strip() or row.note.strip() or row.price.strip()):
            continue
        shown.append(row)
        try:
            price = parse_cents(row.price)
        except ValueError:
            error, price = "Quoted prices must be amounts like 89.99.", None
        if not row.description.strip():
            error = error or "Every recommended item needs a description."
        elif len(row.description.strip()) > 200:
            error = error or "A recommended item's description is too long."
        clean.append((row.description.strip(), row.note.strip(), price))
    return shown, clean, error


@router.post("/invoices/{doc_id}/save", dependencies=[Depends(same_origin)])
async def save(request: Request, db: DbSession, user: SignedInUser, doc_id: uuid.UUID) -> Response:
    doc, _parsed = get_pending(db, user, doc_id)
    if doc.car_id is None:
        raise HTTPException(status_code=422, detail="Choose a car first")
    car = cars.get_car(db, user, doc.car_id)
    data = await request.form()
    declined_shown, declined, row_error = read_declined(data)
    form = await read_form(request, allow_no_items=bool(declined), done_by="shop")
    form.document_id = str(doc.id)
    if form.errors or row_error:
        return review_page(request, db, user, doc, form, declined_shown, row_errors=row_error)

    duplicate = find_duplicate(db, user, form.shop, form.ro_number)
    if duplicate is not None and data.get("confirm_duplicate") != "yes":
        return review_page(request, db, user, doc, form, declined_shown, duplicate=duplicate)

    has_items = any(not i.is_blank() for i in form.items)
    record = None
    if has_items:
        record = service.save_record(db, car, form, document_id=doc.id)
        due.close_open(db, car.id, {i.type for i in record.items} & set(due.FOLLOW_UP_TYPES))
    elif form.miles_value is not None:
        db.add(MileageReading(car_id=car.id, on=form.on_date, miles=form.miles_value))
    for description, note, price in declined:
        db.add(
            RecommendedItem(
                car_id=car.id,
                description=description,
                shop_note=note or None,
                price_cents=price,
                recommended_on=form.on_date,
                recommended_miles=form.miles_value,
                document_id=doc.id,
            )
        )
    doc.status, doc.parsed = "attached", None
    audit.record(db, "invoice_imported", user_id=user.id, document_id=str(doc.id))
    db.commit()
    if record is not None:
        return RedirectResponse(f"/service/{record.id}?saved=1", status_code=303)
    return RedirectResponse("/todo", status_code=303)


@router.get("/documents", response_class=HTMLResponse)
def documents_list(request: Request, db: DbSession, user: SignedInUser) -> HTMLResponse:
    car = cars.selected_car(db, user)
    docs = []
    if car:
        docs = list(
            db.scalars(
                select(Document)
                .where(Document.car_id == car.id)
                .order_by(Document.created_at.desc())
            )
        )
    return render(
        request,
        "pages/documents.html",
        title="Documents",
        user=user,
        active="more",
        db=db,
        car=car,
        docs=docs,
    )


@router.get("/documents/{doc_id}/file")
def document_file(db: DbSession, user: SignedInUser, doc_id: uuid.UUID) -> Response:
    doc = documents.get_document(db, user, doc_id)
    try:
        data = storage.load(doc.storage_ref)
    except storage.StorageError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="invoice.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
