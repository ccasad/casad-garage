"""EncryptedText and EncryptedJSON never put plain text in the database."""

from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.models import EncryptedJSON, EncryptedText


class Base(DeclarativeBase):
    pass


class Secret(Base):
    __tablename__ = "secrets_under_test"

    id: Mapped[int] = mapped_column(primary_key=True)
    note: Mapped[str] = mapped_column(EncryptedText)
    data: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON)


def test_encrypted_columns_round_trip_and_store_no_plain_text():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Secret(id=1, note="Alex's private note", data={"weight": 72}))
        db.commit()

        raw_note, raw_data = db.execute(text("SELECT note, data FROM secrets_under_test")).one()
        assert b"private note" not in bytes(raw_note)
        assert b"weight" not in bytes(raw_data)

        db.expire_all()
        secret = db.get(Secret, 1)
        assert secret.note == "Alex's private note"
        assert secret.data == {"weight": 72}
