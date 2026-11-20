"""Business operations. Routers stay thin; the seed script and tests reuse these."""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import billing
from .errors import ApiError
from .models import Bill, Payment, Subscriber, UsageRecord

TWO_PLACES = Decimal("0.01")

UNIT_PER_EVENT = {
    "Phone": billing.MINUTES_PER_PHONE_EVENT,
    "Internet": billing.MB_PER_INTERNET_EVENT,
}
UNIT_NAME = {"Phone": "minutes", "Internet": "MB"}


def get_subscriber(db: Session, subscriber_no: str) -> Subscriber:
    sub = db.scalar(select(Subscriber).where(Subscriber.subscriber_no == subscriber_no))
    if sub is None:
        raise ApiError(404, "SUBSCRIBER_NOT_FOUND", f"Subscriber {subscriber_no} not found.")
    return sub


def _period_units(db: Session, subscriber_id: int, year: int, month: int, usage_type: str) -> int:
    total = db.scalar(
        select(func.coalesce(func.sum(UsageRecord.units), 0)).where(
            UsageRecord.subscriber_id == subscriber_id,
            UsageRecord.year == year,
            UsageRecord.month == month,
            UsageRecord.usage_type == usage_type,
        )
    )
    return int(total or 0)


def add_usage(
    db: Session, subscriber_no: str, year: int, month: int, usage_type: str, count: int
) -> tuple[UsageRecord, int]:
    sub = get_subscriber(db, subscriber_no)
    record = UsageRecord(
        subscriber_id=sub.id,
        year=year,
        month=month,
        usage_type=usage_type,
        event_count=count,
        units=count * UNIT_PER_EVENT[usage_type],
    )
    db.add(record)
    db.commit()
    return record, _period_units(db, sub.id, year, month, usage_type)


def find_bill(db: Session, subscriber_no: str, year: int, month: int, lock: bool = False) -> Bill:
    """Used by public and protected lookups. Unknown subscriber and 'not calculated yet'
    return the same error so the public Query Bill route cannot be used to enumerate
    subscriber numbers."""
    stmt = (
        select(Bill)
        .join(Subscriber, Bill.subscriber_id == Subscriber.id)
        .where(
            Subscriber.subscriber_no == subscriber_no,
            Bill.year == year,
            Bill.month == month,
        )
    )
    if lock:
        stmt = stmt.with_for_update(of=Bill)
    bill = db.scalar(stmt)
    if bill is None:
        raise ApiError(
            404,
            "BILL_NOT_FOUND",
            f"No calculated bill for subscriber {subscriber_no} in {month:02d}/{year}.",
        )
    return bill


def calculate_bill(db: Session, subscriber_no: str, year: int, month: int) -> tuple[Bill, bool]:
    sub = get_subscriber(db, subscriber_no)
    minutes = _period_units(db, sub.id, year, month, "Phone")
    mb = _period_units(db, sub.id, year, month, "Internet")
    amounts = billing.compute_bill(minutes, mb)

    bill = db.scalar(
        select(Bill)
        .where(Bill.subscriber_id == sub.id, Bill.year == year, Bill.month == month)
        .with_for_update()
    )
    recalculated = bill is not None
    if bill is None:
        bill = Bill(
            subscriber_id=sub.id,
            year=year,
            month=month,
            paid_amount=Decimal("0.00"),
        )
        db.add(bill)
    elif bill.paid_amount > 0:
        # Rewriting the total under an existing payment would break the balance.
        raise ApiError(
            409,
            "BILL_LOCKED",
            "This bill already has payments and cannot be recalculated.",
        )

    bill.phone_minutes = minutes
    bill.internet_mb = mb
    bill.phone_charge = amounts.phone_charge
    bill.internet_charge = amounts.internet_charge
    bill.total = amounts.total
    bill.status = billing.bill_status(bill.total, bill.paid_amount)
    db.commit()
    return bill, recalculated


def pay_bill(
    db: Session,
    subscriber_no: str,
    year: int,
    month: int,
    amount: Decimal,
    transaction_id: str,
) -> Bill:
    amount = amount.quantize(TWO_PLACES)
    bill = find_bill(db, subscriber_no, year, month, lock=True)

    if db.scalar(select(Payment.id).where(Payment.transaction_id == transaction_id)):
        raise ApiError(
            409, "DUPLICATE_TRANSACTION", f"Transaction ID {transaction_id} was already used."
        )

    remaining = bill.total - bill.paid_amount
    if remaining <= 0:
        raise ApiError(409, "BILL_ALREADY_PAID", "This bill is already fully paid.")
    if amount > remaining:
        raise ApiError(
            400,
            "AMOUNT_EXCEEDS_BALANCE",
            f"Payment of {amount} exceeds the remaining balance of {remaining}.",
        )

    db.add(Payment(bill_id=bill.id, transaction_id=transaction_id, amount=amount))
    bill.paid_amount = bill.paid_amount + amount
    bill.status = billing.bill_status(bill.total, bill.paid_amount)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(
            409, "DUPLICATE_TRANSACTION", f"Transaction ID {transaction_id} was already used."
        )
    return bill
