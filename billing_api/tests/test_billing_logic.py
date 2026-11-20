from datetime import date
from decimal import Decimal

import pytest

from app import billing


@pytest.mark.parametrize(
    "minutes,expected",
    [
        (0, 0),
        (1000, 0),        # exactly the free allowance
        (1001, 10),       # started block is charged in full (guide 2.2)
        (2000, 10),
        (2001, 20),       # guide 2.2 example
        (1350, 10),
    ],
)
def test_phone_charge(minutes, expected):
    assert billing.phone_charge(minutes) == Decimal(expected)


@pytest.mark.parametrize(
    "mb,expected",
    [
        (0, 50),          # base fee even with zero usage (guide 3.1)
        (20_000, 50),     # 20 GB
        (20_001, 60),     # 1 MB over -> full extra block
        (21_000, 60),     # 21 GB
        (30_000, 60),     # 30 GB
        (30_001, 70),
        (35_000, 70),     # 35 GB (guide 3.2)
    ],
)
def test_internet_charge(mb, expected):
    assert billing.internet_charge(mb) == Decimal(expected)


def test_worked_example_is_80_dollars():
    amounts = billing.compute_bill(minutes=1350, mb=35_000)
    assert amounts.phone_charge == Decimal(10)
    assert amounts.internet_charge == Decimal(70)
    assert amounts.total == Decimal(80)


def test_bill_status_transitions():
    total = Decimal("80")
    assert billing.bill_status(total, Decimal("0")) == "UNPAID"
    assert billing.bill_status(total, Decimal("20")) == "PARTIALLY_PAID"
    assert billing.bill_status(total, Decimal("80")) == "PAID"


def test_due_date_is_15_days_after_month_end():
    assert billing.due_date(2026, 10) == date(2026, 11, 15)  # guide 6.1 example
    assert billing.due_date(2026, 12) == date(2027, 1, 15)
    assert billing.due_date(2028, 2) == date(2028, 3, 15)    # leap year
