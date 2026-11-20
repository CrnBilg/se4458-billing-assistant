from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import billing, services
from ..database import get_db
from ..models import Bill, Subscriber, UsageRecord
from ..schemas import (
    BillResponse,
    CalculateBillRequest,
    CalculateBillResponse,
    DetailedBillResponse,
    ErrorResponse,
    InternetBreakdown,
    PhoneBreakdown,
    UsageItem,
    UsagePage,
)
from ..security import Principal, authorize_subscriber, get_principal, require_admin

router = APIRouter(prefix="/bills", tags=["Bills"])

SubscriberPath = Annotated[
    str, Path(pattern=r"^[A-Za-z0-9_-]{1,20}$", description="Subscriber number", examples=["5551001"])
]
YearPath = Annotated[int, Path(ge=2000, le=2100, examples=[2026])]
MonthPath = Annotated[int, Path(ge=1, le=12, examples=[10])]


def _bill_fields(bill: Bill, subscriber_no: str) -> dict:
    return dict(
        subscriberNo=subscriber_no,
        month=bill.month,
        year=bill.year,
        billTotal=bill.total,
        paidAmount=bill.paid_amount,
        remainingBalance=bill.total - bill.paid_amount,
        status=bill.status,
    )


@router.post(
    "/calculate",
    response_model=CalculateBillResponse,
    summary="Calculate Bill (admin only)",
    description="Calculates the bill from recorded usage and stores it. Phone: first 1,000 minutes "
    "free, then $10 per started 1,000-minute block. Internet: $50 up to 20 GB, then $10 per started "
    "10 GB block (1 GB = 1,000 MB). Recalculating is allowed until the first payment is recorded.",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def calculate_bill(
    body: CalculateBillRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[Principal, Depends(require_admin)],
):
    bill, recalculated = services.calculate_bill(db, body.subscriberNo, body.year, body.month)
    return CalculateBillResponse(
        status="SUCCESS",
        subscriberNo=body.subscriberNo,
        month=body.month,
        year=body.year,
        total=bill.total,
        recalculated=recalculated,
    )


@router.get(
    "/{subscriber_no}/{year}/{month}",
    response_model=BillResponse,
    summary="Query Bill (no authentication, per assignment table)",
    description="Returns the stored bill total, paid amount, remaining balance and status.",
    responses={404: {"model": ErrorResponse}},
)
def query_bill(
    subscriber_no: SubscriberPath,
    year: YearPath,
    month: MonthPath,
    db: Annotated[Session, Depends(get_db)],
):
    bill = services.find_bill(db, subscriber_no, year, month)
    return BillResponse(**_bill_fields(bill, subscriber_no))


@router.get(
    "/{subscriber_no}/{year}/{month}/detailed",
    response_model=DetailedBillResponse,
    summary="Query Bill Detailed (authenticated, paged usage list)",
    description="Bill summary plus usage and charge breakdown. The usage records are paged with "
    "`page` and `pageSize`. A subscriber can only read their own bill.",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def query_bill_detailed(
    subscriber_no: SubscriberPath,
    year: YearPath,
    month: MonthPath,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    page: Annotated[int, Query(ge=1)] = 1,
    pageSize: Annotated[int, Query(ge=1, le=100)] = 20,
):
    authorize_subscriber(principal, subscriber_no)
    bill = services.find_bill(db, subscriber_no, year, month)

    base = (
        select(UsageRecord)
        .join(Subscriber, UsageRecord.subscriber_id == Subscriber.id)
        .where(
            Subscriber.subscriber_no == subscriber_no,
            UsageRecord.year == year,
            UsageRecord.month == month,
        )
    )
    total_items = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    records = db.scalars(
        base.order_by(UsageRecord.id).offset((page - 1) * pageSize).limit(pageSize)
    ).all()

    items = [
        UsageItem(
            id=r.id,
            usageType=r.usage_type,
            events=r.event_count,
            units=r.units,
            unit=services.UNIT_NAME[r.usage_type],
            recordedAt=r.recorded_at,
        )
        for r in records
    ]
    phone = PhoneBreakdown(
        minutes=bill.phone_minutes,
        includedMinutes=billing.PHONE_INCLUDED_MINUTES,
        billableMinutes=max(0, bill.phone_minutes - billing.PHONE_INCLUDED_MINUTES),
        extraBlocks=billing.phone_extra_blocks(bill.phone_minutes),
        charge=bill.phone_charge,
    )
    internet = InternetBreakdown(
        mb=bill.internet_mb,
        gb=bill.internet_mb / 1000,
        includedGb=billing.INTERNET_INCLUDED_MB // 1000,
        baseCharge=billing.INTERNET_BASE_PRICE,
        extraBlocks=billing.internet_extra_blocks(bill.internet_mb),
        additionalCharge=bill.internet_charge - billing.INTERNET_BASE_PRICE,
        charge=bill.internet_charge,
    )
    return DetailedBillResponse(
        **_bill_fields(bill, subscriber_no),
        dueDate=billing.due_date(year, month),
        calculatedAt=bill.calculated_at,
        phone=phone,
        internet=internet,
        usage=UsagePage(
            page=page,
            pageSize=pageSize,
            totalItems=total_items,
            totalPages=-(-total_items // pageSize),
            items=items,
        ),
    )
