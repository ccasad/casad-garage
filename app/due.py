"""Due items and the "due soon" rule (FR-15 to FR-17)."""

import uuid
from collections.abc import Collection, Iterable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mileage
from app.models import DueItem, utcnow

DUE_TYPES = [
    ("registration", "Registration"),
    ("state_inspection", "State inspection"),
    ("emissions_inspection", "Emissions inspection"),
    ("oil_change", "Oil change"),
    ("loan_payoff", "Loan payoff"),
    ("warranty_ends", "Warranty ends"),
    ("other", "Other"),
]
DUE_TYPE_LABELS = dict(DUE_TYPES)

SOON_DAYS = 30
SOON_MILES = 500
# Service types that offer to set the next due item when logged (FR-16).
FOLLOW_UP_TYPES = ("state_inspection", "emissions_inspection", "oil_change")


def today() -> date:
    return utcnow().date()


def status(item: DueItem, current_miles: int | None, on: date | None = None) -> str | None:
    """'overdue', 'soon' or None for an open item. Done items have no status."""
    if item.done_at is not None:
        return None
    on = on or today()
    if item.due_date is not None and item.due_date < on:
        return "overdue"
    if item.due_miles is not None and current_miles is not None and current_miles >= item.due_miles:
        return "overdue"
    if item.due_date is not None and item.due_date <= on + timedelta(days=SOON_DAYS):
        return "soon"
    if (
        item.due_miles is not None
        and current_miles is not None
        and item.due_miles - current_miles <= SOON_MILES
    ):
        return "soon"
    return None


def sort_key(item: DueItem) -> tuple:
    """Soonest first: dated items by date, then mileage-only items by mileage."""
    return (
        item.due_date is None,
        item.due_date or date.max,
        item.due_miles if item.due_miles is not None else 10**9,
        item.created_at,
    )


def open_items(db: Session, car_ids: Collection[uuid.UUID]) -> list[DueItem]:
    if not car_ids:
        return []
    return list(
        db.scalars(select(DueItem).where(DueItem.car_id.in_(car_ids), DueItem.done_at.is_(None)))
    )


def due_soon_by_car(
    db: Session, car_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[DueItem, str]]]:
    """Each car's overdue or due-soon open items, soonest first."""
    current = mileage.current_mileage(db, car_ids)
    out: dict[uuid.UUID, list[tuple[DueItem, str]]] = {}
    for item in sorted(open_items(db, car_ids), key=sort_key):
        reading = current.get(item.car_id)
        state = status(item, reading.miles if reading else None)
        if state:
            out.setdefault(item.car_id, []).append((item, state))
    return out


def due_soon_car_ids(db: Session, car_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    return set(due_soon_by_car(db, car_ids))


def close_open(db: Session, car_id: uuid.UUID, types: Iterable[str]) -> None:
    """Close open manual due items of these types on a car: the work has been done."""
    types = list(types)
    if not types:
        return
    now = utcnow()
    for item in db.scalars(
        select(DueItem).where(
            DueItem.car_id == car_id,
            DueItem.type.in_(types),
            DueItem.done_at.is_(None),
            DueItem.source == "manual",
        )
    ):
        item.done_at = now
