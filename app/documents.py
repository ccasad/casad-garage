"""Access to uploaded documents (invoice PDFs), which are never publicly reachable
(NFR-14): they are served only through the app, to people who can see the car."""

import uuid

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import cars
from app.models import Car, Document, User


def visible_documents_query(user: User):
    """Documents on cars the user can see, plus the user's own not-yet-matched uploads."""
    return (
        select(Document)
        .outerjoin(Car, Car.id == Document.car_id)
        .where(
            or_(
                and_(Document.car_id.is_not(None), cars.visible_filter(user)),
                and_(Document.car_id.is_(None), Document.uploaded_by_id == user.id),
            )
        )
    )


def get_document(
    db: Session, user: User, document_id: uuid.UUID, *, missing_ok: bool = False
) -> Document | None:
    doc = db.scalar(visible_documents_query(user).where(Document.id == document_id))
    if doc is None and not missing_ok:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
