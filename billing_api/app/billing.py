"""Pure billing rules (no database, no HTTP) -- Mobile_Provider_Billing_Guide.md sections 2-4.

All usage is held as integers (minutes, MB) so rounding never depends on floats:
    phone    = $10 * ceil(max(0, minutes - 1000) / 1000)
    internet = $50 + $10 * ceil(max(0, GB - 20) / 10), with 1 GB = 1000 MB
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

PHONE_INCLUDED_MINUTES = 1000
PHONE_BLOCK_MINUTES = 1000
PHONE_BLOCK_PRICE = Decimal("10.00")

INTERNET_BASE_PRICE = Decimal("50.00")
INTERNET_INCLUDED_MB = 20 * 1000
INTERNET_BLOCK_MB = 10 * 1000
INTERNET_BLOCK_PRICE = Decimal("10.00")

MINUTES_PER_PHONE_EVENT = 10
MB_PER_INTERNET_EVENT = 1

DUE_DAYS_AFTER_MONTH_END = 15


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def phone_extra_blocks(minutes: int) -> int:
    return _ceil_div(max(0, minutes - PHONE_INCLUDED_MINUTES), PHONE_BLOCK_MINUTES)


def internet_extra_blocks(mb: int) -> int:
    return _ceil_div(max(0, mb - INTERNET_INCLUDED_MB), INTERNET_BLOCK_MB)


def phone_charge(minutes: int) -> Decimal:
    return PHONE_BLOCK_PRICE * phone_extra_blocks(minutes)


def internet_charge(mb: int) -> Decimal:
    return INTERNET_BASE_PRICE + INTERNET_BLOCK_PRICE * internet_extra_blocks(mb)


@dataclass(frozen=True)
class BillAmounts:
    phone_charge: Decimal
    internet_charge: Decimal

    @property
    def total(self) -> Decimal:
        return self.phone_charge + self.internet_charge


def compute_bill(minutes: int, mb: int) -> BillAmounts:
    return BillAmounts(phone_charge(minutes), internet_charge(mb))


def bill_status(total: Decimal, paid: Decimal) -> str:
    if paid <= 0:
        return "UNPAID"
    if paid < total:
        return "PARTIALLY_PAID"
    return "PAID"


def due_date(year: int, month: int) -> date:
    """Due 15 calendar days after the end of the billing month (Oct 2026 -> Nov 15, 2026)."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day) + timedelta(days=DUE_DAYS_AFTER_MONTH_END)
