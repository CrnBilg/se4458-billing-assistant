"""Demo data for the instructor and the agent demos.

    python -m app.seed

Creates one admin and two subscribers plus usage/bills for Sep and Oct 2026:
  5551001 (password: ayse123)   Oct 2026: 1,350 min + 35,000 MB  -> $80 (the guide's worked example)
                                Sep 2026: 800 min + 15,000 MB    -> $50, partly paid
  5551002 (password: mehmet123) Oct 2026: 500 min + 22,000 MB    -> $60
  ADMIN   (password: admin123)
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, services
from .database import Base, get_engine
from .security import hash_password

USERS = [
    ("ADMIN", "Billing Admin", "admin", "admin123"),
    ("5551001", "Ayse Demir", "subscriber", "ayse123"),
    ("5551002", "Mehmet Kaya", "subscriber", "mehmet123"),
]

# (subscriber, year, month, phone_events (x10 min), internet_events (x1 MB))
USAGE = [
    ("5551001", 2026, 10, 135, 35_000),
    ("5551001", 2026, 9, 80, 15_000),
    ("5551002", 2026, 10, 50, 22_000),
]


def seed(db: Session) -> None:
    for no, name, role, password in USERS:
        exists = db.scalar(select(models.Subscriber).where(models.Subscriber.subscriber_no == no))
        if not exists:
            db.add(
                models.Subscriber(
                    subscriber_no=no, name=name, role=role, password_hash=hash_password(password)
                )
            )
    db.commit()

    for no, year, month, phone_events, internet_events in USAGE:
        sub = services.get_subscriber(db, no)
        already = db.scalar(
            select(models.UsageRecord.id).where(
                models.UsageRecord.subscriber_id == sub.id,
                models.UsageRecord.year == year,
                models.UsageRecord.month == month,
            )
        )
        if already:
            continue
        services.add_usage(db, no, year, month, "Phone", phone_events)
        services.add_usage(db, no, year, month, "Internet", internet_events)
        services.calculate_bill(db, no, year, month)

    # A partial payment on the September bill so the demo has a PARTIALLY_PAID example.
    sep = services.find_bill(db, "5551001", 2026, 9)
    if sep.paid_amount == 0:
        services.pay_bill(db, "5551001", 2026, 9, Decimal("20.00"), "SEED-TX-0001")


if __name__ == "__main__":
    from sqlalchemy.orm import sessionmaker

    engine = get_engine()
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        seed(session)
    print("Seed complete.")
