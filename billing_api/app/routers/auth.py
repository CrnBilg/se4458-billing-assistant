from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import ApiError
from ..models import Subscriber
from ..schemas import ErrorResponse, TokenRequest, TokenResponse
from ..security import create_token, verify_password

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Get a JWT access token",
    responses={401: {"model": ErrorResponse}},
)
def issue_token(body: TokenRequest, db: Annotated[Session, Depends(get_db)]):
    sub = db.scalar(select(Subscriber).where(Subscriber.subscriber_no == body.subscriberNo))
    # Same message for unknown user and wrong password (no account enumeration).
    if sub is None or not verify_password(body.password, sub.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid subscriber number or password.")
    token, expires_in = create_token(sub.subscriber_no, sub.role)
    return TokenResponse(accessToken=token, expiresIn=expires_in)
