"""ER model: Subscriber 1-N UsageRecord, Subscriber 1-N Bill, Bill 1-N Payment."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscriber_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    # "subscriber" (a customer) or "admin" (provider back-office)
    role: Mapped[str] = mapped_column(String(20), default="subscriber")
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageRecord(Base):
    """One Add Usage call. `units` = minutes (Phone) or MB (Internet)."""

    __tablename__ = "usage_records"
    __table_args__ = (Index("ix_usage_period", "subscriber_id", "year", "month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subscriber_id: Mapped[int] = mapped_column(ForeignKey("subscribers.id"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    usage_type: Mapped[str] = mapped_column(String(10))  # Phone | Internet
    event_count: Mapped[int] = mapped_column(Integer)
    units: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Bill(Base):
    __tablename__ = "bills"
    __table_args__ = (
        UniqueConstraint("subscriber_id", "year", "month", name="uq_bill_period"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    subscriber_id: Mapped[int] = mapped_column(ForeignKey("subscribers.id"))
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    phone_minutes: Mapped[int] = mapped_column(Integer)
    internet_mb: Mapped[int] = mapped_column(Integer)
    phone_charge: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    internet_charge: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(20), default="UNPAID")
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    subscriber: Mapped[Subscriber] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="bill")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("bills.id"), index=True)
    # Unique across the whole system -> duplicate transaction IDs are rejected.
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bill: Mapped[Bill] = relationship(back_populates="payments")
