"""Mileage readings and the car's current mileage (FR-10, FR-11)."""

import uuid
from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MileageReading


def current_mileage(db: Session, car_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, MileageReading]:
    """The newest reading by date for each car (ties: the one saved last)."""
    if not car_ids:
        return {}
    rows = db.scalars(
        select(MileageReading)
        .where(MileageReading.car_id.in_(car_ids))
        .order_by(MileageReading.on.desc(), MileageReading.created_at.desc())
    )
    newest: dict[uuid.UUID, MileageReading] = {}
    for reading in rows:
        newest.setdefault(reading.car_id, reading)
    return newest
