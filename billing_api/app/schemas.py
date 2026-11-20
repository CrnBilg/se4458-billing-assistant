from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer, field_validator

# Money is stored as Decimal and rendered as a JSON number with 2 decimals max.
Money = Annotated[
    Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")
]

SubscriberNo = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,20}$", examples=["5551001"])]
Month = Annotated[int, Field(ge=1, le=12, examples=[10])]
Year = Annotated[int, Field(ge=2000, le=2100, examples=[2026])]


# ---- errors ---------------------------------------------------------------
class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---- auth -----------------------------------------------------------------
class TokenRequest(BaseModel):
    subscriberNo: SubscriberNo
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    accessToken: str
    tokenType: str = "Bearer"
    expiresIn: int


# ---- add usage ------------------------------------------------------------
class AddUsageRequest(BaseModel):
    subscriberNo: SubscriberNo
    month: Month
    year: Year
    usageType: Literal["Phone", "Internet"]
    count: int = Field(
        1,
        ge=1,
        le=1_000_000,
        description="Number of usage events to record (each Phone event = 10 minutes, "
        "each Internet event = 1 MB). Defaults to 1 as in the assignment.",
    )

    @field_validator("usageType", mode="before")
    @classmethod
    def _normalize_type(cls, v):
        return v.strip().capitalize() if isinstance(v, str) else v


class AddUsageResponse(BaseModel):
    status: str
    subscriberNo: str
    month: int
    year: int
    usageType: str
    eventsAdded: int
    unitsAdded: int
    unit: str
    periodTotalUnits: int


# ---- calculate bill -------------------------------------------------------
class CalculateBillRequest(BaseModel):
    subscriberNo: SubscriberNo
    month: Month
    year: Year


class CalculateBillResponse(BaseModel):
    status: str
    subscriberNo: str
    month: int
    year: int
    total: Money
    recalculated: bool


# ---- query bill -----------------------------------------------------------
class BillResponse(BaseModel):
    subscriberNo: str
    month: int
    year: int
    billTotal: Money
    paidAmount: Money
    remainingBalance: Money
    status: str


class PhoneBreakdown(BaseModel):
    minutes: int
    includedMinutes: int
    billableMinutes: int
    extraBlocks: int
    charge: Money


class InternetBreakdown(BaseModel):
    mb: int
    gb: float
    includedGb: int
    baseCharge: Money
    extraBlocks: int
    additionalCharge: Money
    charge: Money


class UsageItem(BaseModel):
    id: int
    usageType: str
    events: int
    units: int
    unit: str
    recordedAt: datetime


class UsagePage(BaseModel):
    page: int
    pageSize: int
    totalItems: int
    totalPages: int
    items: list[UsageItem]


class DetailedBillResponse(BillResponse):
    dueDate: date
    calculatedAt: datetime
    phone: PhoneBreakdown
    internet: InternetBreakdown
    usage: UsagePage


# ---- pay bill -------------------------------------------------------------
class PayBillRequest(BaseModel):
    subscriberNo: SubscriberNo
    month: Month
    year: Year
    amount: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    transactionId: str = Field(min_length=1, max_length=64)


class PayBillResponse(BaseModel):
    status: str
    transactionId: str
    subscriberNo: str
    month: int
    year: int
    paidAmount: Money
    totalPaid: Money
    remainingBalance: Money
    billStatus: str
