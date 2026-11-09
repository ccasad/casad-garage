import json
import uuid
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app import crypto


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("naive datetime")
            value = value.astimezone(UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class EncryptedText(TypeDecorator[str]):
    """Text encrypted with TOKEN_ENCRYPTION_KEY before it reaches the database."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> bytes | None:
        return None if value is None else crypto.encrypt(value)

    def process_result_value(self, value: bytes | None, dialect: Any) -> str | None:
        return None if value is None else crypto.decrypt(value)


class EncryptedJSON(TypeDecorator[dict[str, Any]]):
    """A JSON document encrypted before it reaches the database."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: dict[str, Any] | None, dialect: Any) -> bytes | None:
        if value is None:
            return None
        return crypto.encrypt(json.dumps(value, separators=(",", ":"), ensure_ascii=False))

    def process_result_value(self, value: bytes | None, dialect: Any) -> dict[str, Any] | None:
        return None if value is None else json.loads(crypto.decrypt(value))


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: UTCDateTime,
        dict[str, Any]: JSON,
        list[str]: JSON,
    }


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="member")
    # "dark" (default), "light" or "system" (follow the device)
    theme: Mapped[str] = mapped_column(String(10), default="dark", server_default="dark")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Set at sign-in and when the session is touched (at most once a minute), so the
    # admin can see who uses the app. Sessions themselves are deleted once idle.
    last_active_at: Mapped[datetime | None]

    passkeys: Mapped[list["Passkey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class Passkey(Base):
    __tablename__ = "passkeys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(default=0)
    transports: Mapped[list[str]] = mapped_column(default=list)
    backed_up: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_used_at: Mapped[datetime | None]

    user: Mapped[User] = relationship(back_populates="passkeys")


class Invite(Base):
    """A one-time link that lets someone set up a passkey for an account."""

    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]

    def is_pending(self, now: datetime) -> bool:
        return self.used_at is None and self.revoked_at is None and now < self.expires_at


class AuthChallenge(Base):
    """A WebAuthn challenge, deleted as soon as it is used so it can't be replayed."""

    __tablename__ = "auth_challenges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    purpose: Mapped[str] = mapped_column(String(20))
    challenge: Mapped[bytes] = mapped_column(LargeBinary)
    invite_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invites.id", ondelete="CASCADE")
    )
    user_handle: Mapped[bytes | None] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime]


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime]

    user: Mapped[User] = relationship()


class AuditEvent(Base):
    """Security events. `detail` must never contain personal data."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event: Mapped[str] = mapped_column(String(50))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Car(Base):
    """A car. Shared cars are visible to everyone; private ("Only me") ones only to the
    person who added them. Everything attached to a car inherits that visibility."""

    __tablename__ = "cars"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    added_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    visibility: Mapped[str] = mapped_column(String(10), default="shared", server_default="shared")
    nickname: Mapped[str | None] = mapped_column(String(60))
    year: Mapped[int]
    make: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(80))
    trim: Mapped[str | None] = mapped_column(String(80))
    engine: Mapped[str | None] = mapped_column(String(80))
    color: Mapped[str | None] = mapped_column(String(40))
    # Sensitive: encrypted at rest. Matching by VIN uses the keyed hash below.
    vin: Mapped[str | None] = mapped_column(EncryptedText)
    vin_hash: Mapped[bytes | None] = mapped_column(LargeBinary, index=True)
    plate: Mapped[str | None] = mapped_column(EncryptedText)
    title_number: Mapped[str | None] = mapped_column(EncryptedText)
    notes: Mapped[str | None] = mapped_column(EncryptedText)
    # The loan, if any (FR-28): {"lender", "final_date" (ISO), "monthly_cents"}. Encrypted.
    loan: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON)
    # Reference to the photo in file storage; the file is only served through the app.
    photo_ref: Mapped[str | None] = mapped_column(String(500))
    photo_updated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    added_by: Mapped[User] = relationship()

    @property
    def name(self) -> str:
        return self.nickname or f"{self.year} {self.make} {self.model}"

    @property
    def subtitle(self) -> str:
        """Year, make, model and trim, for places that show the nickname as the title."""
        return " ".join(p for p in (str(self.year), self.make, self.model, self.trim) if p)


class UserPrefs(Base):
    """Per-user choices: the car last selected (and, later, the sort order)."""

    __tablename__ = "user_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    selected_car_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cars.id", ondelete="SET NULL")
    )
    # "name", "year" or "serviced" (most recently serviced first)
    car_sort: Mapped[str] = mapped_column(String(10), default="name", server_default="name")


class CarStar(Base):
    """A car a user has starred; stars are personal and only change that user's order."""

    __tablename__ = "car_stars"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    car_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cars.id", ondelete="CASCADE"), primary_key=True
    )


class MileageReading(Base):
    """A dated odometer reading. The newest by date is the car's current mileage."""

    __tablename__ = "mileage_readings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"), index=True)
    on: Mapped[date] = mapped_column(Date)
    miles: Mapped[int]
    # Set when the reading came from saving a service record (FR-11).
    service_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_records.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ServiceRecord(Base):
    """One visit: a date, odometer, shop and the work done."""

    __tablename__ = "service_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"), index=True)
    on: Mapped[date] = mapped_column(Date)
    miles: Mapped[int | None]
    shop: Mapped[str | None] = mapped_column(String(120))
    ro_number: Mapped[str | None] = mapped_column(String(40))
    # Who did the work (FR-12): "shop", or "self" for a do-it-yourself job.
    done_by: Mapped[str] = mapped_column(String(10), default="shop", server_default="shop")
    done_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    total_cents: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(EncryptedText)
    # The invoice PDF this record was imported from.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    done_by_user: Mapped[User | None] = relationship()
    items: Mapped[list["ServiceItem"]] = relationship(
        back_populates="record",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ServiceItem.position",
    )


class ServiceItem(Base):
    __tablename__ = "service_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_records.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(default=0)
    description: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(30), default="other")
    # The brand (the column predates the separate part number).
    part: Mapped[str | None] = mapped_column(String(120))
    part_number: Mapped[str | None] = mapped_column(String(60))
    cost_cents: Mapped[int | None]
    # A warranty on this part (FR-27): months and/or miles from the service
    warranty_months: Mapped[int | None]
    warranty_miles: Mapped[int | None]

    record: Mapped[ServiceRecord] = relationship(back_populates="items")


class DueItem(Base):
    """Something coming up for a car: a date and/or a mileage (FR-15)."""

    __tablename__ = "due_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    due_date: Mapped[date | None] = mapped_column(Date)
    due_miles: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(EncryptedText)
    done_at: Mapped[datetime | None]
    # "manual", or "loan" / "warranty" for items the app keeps in step with the car's loan
    # and a service item's warranty.
    source: Mapped[str] = mapped_column(String(10), default="manual", server_default="manual")
    service_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_items.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Document(Base):
    """An uploaded invoice PDF. The file is in private storage; only a reference is kept.

    Until it is matched to a car, only the person who uploaded it can see it."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cars.id", ondelete="CASCADE"), index=True
    )
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="invoice")
    filename: Mapped[str] = mapped_column(EncryptedText)
    storage_ref: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int]
    # "review": parsed and waiting for the user to check it; "attached": kept with the car
    # without an import (not recognised, or already imported).
    status: Mapped[str] = mapped_column(String(10), default="attached")
    # What the parser found (vehicle and jobs only), kept only until the review is saved.
    parsed: Mapped[dict[str, Any] | None] = mapped_column(EncryptedJSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class RecommendedItem(Base):
    """Work a shop recommended that hasn't been done yet (FR-24)."""

    __tablename__ = "recommended_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    car_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(String(200))
    shop_note: Mapped[str | None] = mapped_column(EncryptedText)
    price_cents: Mapped[int | None]
    recommended_on: Mapped[date | None] = mapped_column(Date)
    recommended_miles: Mapped[int | None]
    # "open", "done" or "dismissed"
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    closed_at: Mapped[datetime | None]
    # The service record that did the work, when linked.
    done_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_records.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
