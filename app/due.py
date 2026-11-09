"""Due items and the "due soon" rule."""

import uuid
from collections.abc import Collection

from sqlalchemy.orm import Session


def due_soon_car_ids(db: Session, car_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    return set()
