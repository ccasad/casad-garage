import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


def record(db: Session, event: str, user_id: uuid.UUID | None = None, **detail: Any) -> None:
    """Add an audit event to the current transaction; the caller commits.

    Never pass personal data in `detail`: IDs, reasons and roles only.
    """
    db.add(AuditEvent(event=event, user_id=user_id, detail=detail))
