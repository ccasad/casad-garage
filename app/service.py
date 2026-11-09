"""Service records: cleaning the form, saving, and "last done" per type (FR-11 to FR-14)."""

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.forms import cents_text, parse_cents, parse_date, parse_miles
from app.models import Car, MileageReading, ServiceItem, ServiceRecord
from app.service_types import SERVICE_TYPE_LABELS


@dataclass
class ItemInput:
    description: str = ""
    type: str = "other"
    part: str = ""
    cost: str = ""
    id: str = ""
    cost_cents: int | None = None

    def is_blank(self) -> bool:
        return not (self.description.strip() or self.part.strip() or self.cost.strip())


@dataclass
class ServiceForm:
    on: str = ""
    miles: str = ""
    shop: str = ""
    ro_number: str = ""
    total: str = ""
    notes: str = ""
    items: list[ItemInput] = field(default_factory=lambda: [ItemInput()])
    errors: dict[str, str] = field(default_factory=dict)
    on_date: date | None = None
    miles_value: int | None = None
    total_cents: int | None = None

    @classmethod
    def from_record(cls, record: ServiceRecord) -> "ServiceForm":
        return cls(
            on=record.on.isoformat(),
            miles=str(record.miles) if record.miles is not None else "",
            shop=record.shop or "",
            ro_number=record.ro_number or "",
            total=cents_text(record.total_cents),
            notes=record.notes or "",
            items=[
                ItemInput(i.description, i.type, i.part or "", cents_text(i.cost_cents), str(i.id))
                for i in record.items
            ]
            or [ItemInput()],
        )

    def clean(self) -> "ServiceForm":
        self.shop, self.ro_number = self.shop.strip(), self.ro_number.strip()
        try:
            self.on_date = parse_date(self.on)
        except ValueError as exc:
            self.errors["on"] = str(exc)
        try:
            self.miles_value = parse_miles(self.miles, required=False)
        except ValueError as exc:
            self.errors["miles"] = str(exc)
        try:
            self.total_cents = parse_cents(self.total)
        except ValueError as exc:
            self.errors["total"] = str(exc)
        if len(self.shop) > 120:
            self.errors["shop"] = "Keep this under 120 characters."
        if len(self.ro_number) > 40:
            self.errors["ro_number"] = "Keep this under 40 characters."
        if len(self.notes) > 4000:
            self.errors["notes"] = "Keep notes under 4000 characters."
        kept = [item for item in self.items if not item.is_blank()]
        for item in kept:
            item.description = item.description.strip()
            item.part = item.part.strip()
            if item.type not in SERVICE_TYPE_LABELS:
                item.type = "other"
            if not item.description:
                self.errors.setdefault("rows", "Every item needs a description.")
            elif len(item.description) > 200 or len(item.part) > 120:
                self.errors.setdefault("rows", "An item description or part is too long.")
            try:
                item.cost_cents = parse_cents(item.cost)
            except ValueError:
                self.errors.setdefault("rows", "Item costs must be amounts like 89.99.")
        if not kept and "rows" not in self.errors:
            self.errors.setdefault("rows", "Add at least one item.")
        self.items = kept or [ItemInput()]
        return self


def build_items(
    ids: list[str], descriptions: list[str], types: list[str], parts: list[str], costs: list[str]
) -> list[ItemInput]:
    """Zip the parallel lists a browser submits for the item rows."""
    count = max(len(descriptions), len(types), len(parts), len(costs), len(ids))
    pad = lambda values: [*values, *[""] * (count - len(values))]
    ids, descriptions, types, parts, costs = map(pad, (ids, descriptions, types, parts, costs))
    return [
        ItemInput(descriptions[i], types[i] or "other", parts[i], costs[i], ids[i])
        for i in range(count)
    ]


def save_record(
    db: Session, car: Car, form: ServiceForm, record: ServiceRecord | None = None
) -> ServiceRecord:
    """Create or update a record from a cleaned form, and keep its odometer reading."""
    if record is None:
        record = ServiceRecord(car_id=car.id, on=form.on_date)
        db.add(record)
    record.on = form.on_date
    record.miles = form.miles_value
    record.shop = form.shop or None
    record.ro_number = form.ro_number or None
    record.notes = form.notes.strip() or None
    total = form.total_cents
    if total is None:
        costs = [i.cost_cents for i in form.items if i.cost_cents is not None]
        total = sum(costs) if costs else None
    record.total_cents = total

    existing = {str(i.id): i for i in record.items}
    keep: list[ServiceItem] = []
    for position, data in enumerate(form.items):
        item = existing.pop(data.id, None) or ServiceItem()
        item.position = position
        item.description = data.description
        item.type = data.type
        item.part = data.part or None
        item.cost_cents = data.cost_cents
        keep.append(item)
    record.items[:] = keep  # items left in `existing` are deleted (delete-orphan)
    db.flush()
    sync_reading(db, record)
    return record


def sync_reading(db: Session, record: ServiceRecord) -> None:
    """Saving a service record adds its odometer reading automatically (FR-11)."""
    reading = db.scalar(select(MileageReading).where(MileageReading.service_record_id == record.id))
    if record.miles is None:
        if reading:
            db.delete(reading)
        return
    if reading is None:
        reading = MileageReading(car_id=record.car_id, service_record_id=record.id)
        db.add(reading)
    reading.on, reading.miles = record.on, record.miles


def records_for_car(db: Session, car_id: uuid.UUID) -> list[ServiceRecord]:
    return list(
        db.scalars(
            select(ServiceRecord)
            .where(ServiceRecord.car_id == car_id)
            .options(selectinload(ServiceRecord.items))
            .order_by(ServiceRecord.on.desc(), ServiceRecord.created_at.desc())
        )
    )


def last_done(records: list[ServiceRecord]) -> list[tuple[str, ServiceRecord]]:
    """For each service type that has been done, the latest record (FR-14), in list order."""
    latest: dict[str, ServiceRecord] = {}
    for record in records:  # newest first
        for item in record.items:
            latest.setdefault(item.type, record)
    return [(key, latest[key]) for key in SERVICE_TYPE_LABELS if key in latest]


def filter_records(
    records: list[ServiceRecord], *, type_: str = "", query: str = ""
) -> list[ServiceRecord]:
    query = query.strip().lower()
    out = []
    for record in records:
        if type_ and not any(i.type == type_ for i in record.items):
            continue
        if query:
            haystack = " ".join(
                [record.shop or "", record.ro_number or "", record.notes or ""]
                + [f"{i.description} {i.part or ''}" for i in record.items]
            ).lower()
            if query not in haystack:
                continue
        out.append(record)
    return out
