"""Which cars a user may see, and the helpers every car route builds on.

Every query for cars, or anything attached to a car, goes through here, so a private
("Only me") car and its records are only ever visible to the person who added it."""

import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app import due, mileage, service, storage
from app.models import Car, CarStar, Document, ServiceRecord, User, UserPrefs
from app.service_types import SERVICE_TYPE_LABELS

TAB_PATHS = ("/", "/service", "/due", "/todo", "/mileage", "/documents", "/cars")


def visible_filter(user: User):
    return or_(Car.visibility == "shared", Car.added_by_id == user.id)


def visible_cars_query(user: User) -> Select[tuple[Car]]:
    return select(Car).where(visible_filter(user))


def get_car(db: Session, user: User, car_id: uuid.UUID) -> Car:
    """The car, or 404: a car you can't see looks exactly like one that doesn't exist."""
    car = db.scalar(visible_cars_query(user).where(Car.id == car_id))
    if car is None:
        raise HTTPException(status_code=404, detail="Car not found")
    return car


def get_prefs(db: Session, user: User) -> UserPrefs:
    prefs = db.get(UserPrefs, user.id)
    if prefs is None:
        prefs = UserPrefs(user_id=user.id)
        db.add(prefs)
        db.flush()
    return prefs


SORTS = [("name", "Name"), ("year", "Year"), ("serviced", "Recently serviced")]


def ordered_cars(db: Session, user: User) -> Sequence[Car]:
    """The user's visible cars: starred first, then their chosen sort (FR-9)."""
    cars = list(db.scalars(visible_cars_query(user)))
    prefs = db.get(UserPrefs, user.id)
    sort = prefs.car_sort if prefs else "name"
    starred = starred_ids(db, user)

    def by_name(car: Car) -> tuple:
        return (car.name.lower(), str(car.id))

    if sort == "year":
        cars.sort(key=lambda c: (-c.year, *by_name(c)))
    elif sort == "serviced":
        last = dict(
            db.execute(
                select(ServiceRecord.car_id, func.max(ServiceRecord.on)).group_by(
                    ServiceRecord.car_id
                )
            ).all()
        )
        # Most recently serviced first; cars never serviced last.
        cars.sort(
            key=lambda c: (
                last.get(c.id) is None,
                -(last[c.id].toordinal()) if c.id in last else 0,
                *by_name(c),
            )
        )
    else:
        cars.sort(key=by_name)
    cars.sort(key=lambda c: c.id not in starred)  # stable: starred first, order kept
    return cars


def selected_car(db: Session, user: User) -> Car | None:
    """The user's remembered car, if they can still see it."""
    prefs = db.get(UserPrefs, user.id)
    if prefs is None or prefs.selected_car_id is None:
        return None
    return db.scalar(visible_cars_query(user).where(Car.id == prefs.selected_car_id))


def select_car(db: Session, user: User, car: Car | None) -> None:
    get_prefs(db, user).selected_car_id = car.id if car else None


def starred_ids(db: Session, user: User) -> set[uuid.UUID]:
    return set(db.scalars(select(CarStar.car_id).where(CarStar.user_id == user.id)))


def toggle_star(db: Session, user: User, car: Car) -> bool:
    """Star or unstar a car for this user only. Returns whether it is now starred."""
    star = db.get(CarStar, (user.id, car.id))
    if star:
        db.delete(star)
        return False
    db.add(CarStar(user_id=user.id, car_id=car.id))
    return True


def can_delete(user: User, car: Car) -> bool:
    return user.is_admin or car.added_by_id == user.id


def delete_car_files(db: Session, car: Car) -> None:
    """Remove stored files (photo, invoices) before the rows go."""
    storage.remove(car.photo_ref)
    for ref in db.scalars(select(Document.storage_ref).where(Document.car_id == car.id)):
        storage.remove(ref)


def delete_user_files(db: Session, user: User) -> None:
    """Remove the stored files of everything an account deletion will cascade away:
    photos and invoices of the cars the user added, and invoices they uploaded."""
    for car in db.scalars(select(Car).where(Car.added_by_id == user.id)):
        delete_car_files(db, car)
    for ref in db.scalars(select(Document.storage_ref).where(Document.uploaded_by_id == user.id)):
        storage.remove(ref)


def overview_context(db: Session, car: Car) -> dict:
    records = service.records_for_car(db, car.id)
    return {
        "current": mileage.current_mileage(db, [car.id]).get(car.id),
        "last_done": service.last_done(records),
        "type_labels": SERVICE_TYPE_LABELS,
        "due_labels": due.DUE_TYPE_LABELS,
        "due_soon": due.due_soon_by_car(db, [car.id]).get(car.id, []),
    }


def card_context(db: Session, cars_: Sequence[Car]) -> dict:
    ids = [c.id for c in cars_]
    return {
        "mileage": mileage.current_mileage(db, ids),
        "due_soon": due.due_soon_by_car(db, ids),
        "due_labels": due.DUE_TYPE_LABELS,
    }
