"""Which cars a user may see, and the helpers every car route builds on.

Every query for cars, or anything attached to a car, goes through here, so a private
("Only me") car and its records are only ever visible to the person who added it."""

import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.models import Car, User, UserPrefs

TAB_PATHS = ("/", "/service", "/due", "/todo", "/mileage", "/documents")


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


def ordered_cars(db: Session, user: User) -> Sequence[Car]:
    """The user's visible cars in their order (starred first, then their chosen sort)."""
    cars = list(db.scalars(visible_cars_query(user)))
    cars.sort(key=lambda c: (c.name.lower(), str(c.id)))
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
    return set()


def can_delete(user: User, car: Car) -> bool:
    return user.is_admin or car.added_by_id == user.id


def delete_car_files(db: Session, car: Car) -> None:
    """Remove stored files (photo, invoices) before the rows go. Added with file storage."""


def overview_context(db: Session, car: Car) -> dict:
    return {}


def card_context(db: Session, cars_: Sequence[Car]) -> dict:
    return {}
