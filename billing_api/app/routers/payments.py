from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import services
from ..database import get_db
from ..schemas import ErrorResponse, PayBillRequest, PayBillResponse
from ..security import Principal, authorize_subscriber, get_principal

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "",
    response_model=PayBillResponse,
    status_code=201,
    summary="Pay Bill (authenticated, simulated)",
    description="Records a simulated partial or full payment. No real card processing. "
    "Duplicate transaction IDs and amounts above the remaining balance are rejected. "
    "A subscriber can only pay their own bill.",
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def pay_bill(
    body: PayBillRequest,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
):
    authorize_subscriber(principal, body.subscriberNo)
    bill = services.pay_bill(
        db, body.subscriberNo, body.year, body.month, body.amount, body.transactionId
    )
    return PayBillResponse(
        status="SUCCESS",
        transactionId=body.transactionId,
        subscriberNo=body.subscriberNo,
        month=body.month,
        year=body.year,
        paidAmount=body.amount,
        totalPaid=bill.paid_amount,
        remainingBalance=bill.total - bill.paid_amount,
        billStatus=bill.status,
    )
