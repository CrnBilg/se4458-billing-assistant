from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db
from ..schemas import AddUsageRequest, AddUsageResponse, ErrorResponse
from ..security import Principal, require_admin

router = APIRouter(prefix="/usage", tags=["Usage"])


@router.post(
    "",
    response_model=AddUsageResponse,
    status_code=201,
    summary="Add Usage (admin only)",
    description="Records usage events for a subscriber and month. One Phone event = 10 minutes, "
    "one Internet event = 1 MB. `count` (default 1) records several events at once.",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def add_usage(
    body: AddUsageRequest,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[Principal, Depends(require_admin)],
):
    record, period_total = services.add_usage(
        db, body.subscriberNo, body.year, body.month, body.usageType, body.count
    )
    return AddUsageResponse(
        status="SUCCESS",
        subscriberNo=body.subscriberNo,
        month=body.month,
        year=body.year,
        usageType=body.usageType,
        eventsAdded=record.event_count,
        unitsAdded=record.units,
        unit=services.UNIT_NAME[body.usageType],
        periodTotalUnits=period_total,
    )
