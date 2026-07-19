"""
Pydantic models for request/response validation and MongoDB documents.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import date, datetime, timedelta, timezone
from typing import Optional, List, Literal
from enum import Enum


class EnquiryStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SOLVED = "solved"


class IssueType(str, Enum):
    MANUFACTURING_DEFECT = "manufacturing_defect"
    HARDNESS_ISSUE = "hardness_issue"
    DAMAGE = "damage"
    EXCHANGE = "exchange"
    OTHER = "other"


# ==================== AUTH ====================
class OTPRequest(BaseModel):
    email: EmailStr
    role: Optional[str] = Field(None, pattern="^(customer|admin)$")


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6, pattern="^[0-9]{6}$")
    role: Optional[str] = Field(None, pattern="^(customer|admin)$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class UserResponse(BaseModel):
    email: str
    role: str
    name: Optional[str] = None
    profile_complete: bool = False
    feedback_required: bool = False
    pending_feedback_piece: Optional[str] = None


# ==================== CUSTOMER ====================
class CustomerProfileCreate(BaseModel):
    """Request body for creating/updating customer profile (email comes from JWT)"""
    name: str
    phone: Optional[str] = None
    address: str
    city: str
    state: Optional[str] = None


class CustomerRegisterRequest(BaseModel):
    """Public customer registration before OTP login is allowed"""
    name: str
    phone: str
    email: EmailStr
    address: str
    city: str
    state: Optional[str] = None


class CustomerProfile(BaseModel):
    """Full customer profile including email"""
    name: str
    email: str
    phone: Optional[str] = None
    address: str
    city: str
    state: Optional[str] = None
    profile_complete: bool = False
    created_at: Optional[datetime] = None


class CustomerProfileResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: Optional[str] = None
    address: str
    city: str
    state: Optional[str] = None
    profile_complete: bool
    created_at: Optional[datetime] = None

    class Config:
        populate_by_name = True


class CustomerDeleteRequest(BaseModel):
    """Require the admin to type the customer's email before permanent deletion."""
    confirmation_email: EmailStr


# ==================== PRODUCT PIECES ====================
class ProductPieceResponse(BaseModel):
    id: str = Field(alias="_id")
    piece: str
    i_code: str
    item_name: str
    describe: Optional[str] = None
    bill: str
    bill_date: datetime
    distributor_code: Optional[int] = None
    distributor_name: Optional[str] = None
    distributor_city: Optional[str] = None
    dealer_code: Optional[int] = None
    dealer_name: Optional[str] = None
    dealer_city: Optional[str] = None
    dealer_state: Optional[str] = None
    dealer_phone: Optional[str] = None
    created_at: datetime

    class Config:
        populate_by_name = True


# ==================== WARRANTY ====================
class WarrantyRuleBase(BaseModel):
    category: str
    warranty_months: int = Field(..., ge=1)
    is_active: bool = True
    terms: List[str] = []


class WarrantyRuleCreate(WarrantyRuleBase):
    pass


class WarrantyRuleUpdate(BaseModel):
    category: Optional[str] = None
    warranty_months: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    terms: Optional[List[str]] = None


class WarrantyRuleResponse(WarrantyRuleBase):
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


class WarrantyRegisterRequest(BaseModel):
    piece: str
    dealer_bill_number: str = Field(..., min_length=1, max_length=120)
    dealer_bill_date: date
    terms_accepted: bool = False

    @field_validator("piece", "dealer_bill_number")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Field is required")
        return value

    @field_validator("dealer_bill_date")
    @classmethod
    def dealer_bill_date_cannot_be_future(cls, value: date) -> date:
        india_timezone = timezone(timedelta(hours=5, minutes=30))
        business_today = datetime.now(india_timezone).date()
        if value > business_today:
            raise ValueError("Customer buying date cannot be in the future")
        return value


class RegistrationDeclineRequest(BaseModel):
    reason: Optional[str] = None


class FlagDaysUpdate(BaseModel):
    old_product_flag_days: int = Field(..., ge=1, le=3650)


RatingChoice = Literal["Very Good", "Good", "Fair", "Poor"]
YesNoChoice = Literal["Yes", "No"]
SourceChoice = Literal["Shop Keeper", "Advertisement", "Retailer", "Visit at Shop"]


class CustomerFeedbackCreate(BaseModel):
    piece: str = Field(..., min_length=1, max_length=120)
    q1: RatingChoice
    q2: SourceChoice
    q3: RatingChoice
    q4: YesNoChoice
    q5: RatingChoice
    q6: RatingChoice
    q7: RatingChoice
    q8: RatingChoice
    q9: RatingChoice
    q10: YesNoChoice
    q11: YesNoChoice
    q12: Optional[str] = Field(None, max_length=3000)
    q13: Optional[str] = Field(None, max_length=3000)
    q14: Optional[str] = Field(None, max_length=3000)

    @field_validator("piece", "q12", "q13", "q14")
    @classmethod
    def clean_feedback_text(cls, value):
        return value.strip() if isinstance(value, str) else value


# ==================== SUPPORT ====================
class SupportContactCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    title: Optional[str] = None
    is_active: bool = True


class SupportContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    title: Optional[str] = None
    is_active: Optional[bool] = None


class RegisteredProductResponse(BaseModel):
    id: str = Field(alias="_id")
    customer_id: str
    piece: str
    item_name: str
    warranty_start: datetime
    warranty_end: datetime
    status: str
    remaining_days: int
    remaining_months: int
    percent_elapsed: float
    registered_at: datetime

    class Config:
        populate_by_name = True


# ==================== ENQUIRY ====================
class EnquiryCreate(BaseModel):
    piece: str
    item_name: str
    issue_type: IssueType
    description: str


class EnquiryStatusUpdate(BaseModel):
    status: EnquiryStatus
    admin_note: Optional[str] = None


class EnquiryResponse(BaseModel):
    id: str = Field(alias="_id")
    customer_id: str
    customer_email: Optional[str] = None
    piece: str
    item_name: str
    issue_type: str
    description: str
    status: str
    admin_note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True


# ==================== IMPORT BATCH ====================
class ImportBatchResponse(BaseModel):
    id: str = Field(alias="_id")
    uploaded_by: str
    uploaded_at: datetime
    booksale_rows: int
    serials_rows: int
    pieces_inserted: int
    pieces_updated: int
    pieces_failed: int
    failed_rows: List[dict] = []

    class Config:
        populate_by_name = True
