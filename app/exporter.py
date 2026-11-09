"""The garage part of "Your data" (NFR-13): every car the user can see, with what is
recorded for it. A private ("Only me") car only ever appears in its owner's download."""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cars
from app.forms import cents_text
from app.models import (
    DueItem,
    MileageReading,
    ServiceRecord,
    User,
    UserPrefs,
)


def iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return value.isoformat()


def garage_data(db: Session, user: User) -> dict[str, Any]:
    visible = cars.ordered_cars(db, user)
    prefs = db.get(UserPrefs, user.id)
    exported_cars = []
    for car in visible:
        exported_cars.append(
            {
                "added_by_me": car.added_by_id == user.id,
                "visibility": car.visibility,
                "nickname": car.nickname,
                "year": car.year,
                "make": car.make,
                "model": car.model,
                "trim": car.trim,
                "engine": car.engine,
                "color": car.color,
                "vin": car.vin,
                "plate": car.plate,
                "notes": car.notes,
                "has_photo": bool(car.photo_ref),
                "mileage_readings": [
                    {"date": iso(r.on), "miles": r.miles}
                    for r in db.scalars(
                        select(MileageReading)
                        .where(MileageReading.car_id == car.id)
                        .order_by(MileageReading.on.desc())
                    )
                ],
                "service_records": [
                    {
                        "date": iso(r.on),
                        "miles": r.miles,
                        "shop": r.shop,
                        "repair_order": r.ro_number,
                        "total": cents_text(r.total_cents),
                        "notes": r.notes,
                        "items": [
                            {
                                "description": i.description,
                                "type": i.type,
                                "part": i.part,
                                "cost": cents_text(i.cost_cents),
                            }
                            for i in r.items
                        ],
                    }
                    for r in db.scalars(
                        select(ServiceRecord)
                        .where(ServiceRecord.car_id == car.id)
                        .order_by(ServiceRecord.on.desc())
                    )
                ],
                "due_items": [
                    {
                        "type": d.type,
                        "due_date": iso(d.due_date),
                        "due_miles": d.due_miles,
                        "notes": d.notes,
                        "done_at": iso(d.done_at),
                    }
                    for d in db.scalars(select(DueItem).where(DueItem.car_id == car.id))
                ],
            }
        )
    return {
        "cars": exported_cars,
        "preferences": {
            "selected_car": next(
                (c.name for c in visible if prefs and c.id == prefs.selected_car_id), None
            )
        },
    }
