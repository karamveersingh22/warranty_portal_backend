"""
MongoDB document models, validation, and index declarations.

These models describe persisted collection documents only. They do not contain
business workflow logic.
"""

from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Union

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from pymongo import ASCENDING, TEXT, IndexModel


class UserRole(str, Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"


class AdminRole(str, Enum):
    ADMIN = "admin"


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


class WarrantyStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"


REQUIRED_WARRANTY_MESSAGE_KEYS = {
    "manufacturing_defect",
    "hardness_issue",
    "damage",
    "exchange",
    "other",
}

MAX_WARRANTY_TERMS = 15


def normalize_email_value(value: Any) -> Any:
    if value is None:
        return value
    return str(value).strip().lower()


def normalize_string_value(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, str):
        return value.strip()
    return value


def validate_required_object_id(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    raise ValueError("Invalid MongoDB ObjectId")


def validate_optional_object_id(value: Any) -> Optional[ObjectId]:
    if value is None:
        return None
    return validate_required_object_id(value)


class MongoDocument(BaseModel):
    """Base document model with Mongo-friendly ObjectId support."""

    id: ObjectId = Field(default_factory=ObjectId, alias="_id")

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
        use_enum_values=True,
        extra="forbid",
    )

    @field_validator("id", mode="before")
    @classmethod
    def validate_object_id(cls, value: Any) -> ObjectId:
        if value is None:
            return ObjectId()
        return validate_required_object_id(value)

    def to_mongo(self) -> Dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class IndexedDocument(MongoDocument):
    collection_name: ClassVar[str]
    indexes: ClassVar[List[IndexModel]] = []


class CustomerDocument(IndexedDocument):
    collection_name: ClassVar[str] = "customers"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("email", ASCENDING)], unique=True),
        IndexModel([("city", ASCENDING)]),
        IndexModel([("created_at", ASCENDING)]),
    ]

    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(..., min_length=1, max_length=30)
    address: str = Field(..., min_length=1, max_length=500)
    city: str = Field(..., min_length=1, max_length=120)
    state: str = Field(..., min_length=1, max_length=120)
    profile_complete: bool = False
    feedback_submitted: bool = False
    created_at: datetime
    updated_at: datetime

    _normalize_strings = field_validator(
        "name", "phone", "address", "city", "state", mode="before"
    )(normalize_string_value)
    _normalize_email = field_validator("email", mode="before")(normalize_email_value)


class AdminUserDocument(IndexedDocument):
    collection_name: ClassVar[str] = "admin_users"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("email", ASCENDING)], unique=True),
        IndexModel([("role", ASCENDING)]),
    ]

    email: EmailStr
    name: str = Field(..., min_length=1, max_length=120)
    role: AdminRole = AdminRole.ADMIN
    created_at: datetime
    updated_at: datetime

    _normalize_strings = field_validator("name", mode="before")(normalize_string_value)
    _normalize_email = field_validator("email", mode="before")(normalize_email_value)


class OTPSessionDocument(IndexedDocument):
    collection_name: ClassVar[str] = "otp_sessions"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("email", ASCENDING), ("role", ASCENDING)], unique=True),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0),
    ]

    email: EmailStr
    role: UserRole
    otp_hash: str = Field(..., min_length=1)
    expires_at: datetime
    resend_count: int = Field(0, ge=0)
    verified: bool = False
    created_at: datetime

    _normalize_email = field_validator("email", mode="before")(normalize_email_value)


class ProductPieceDocument(IndexedDocument):
    collection_name: ClassVar[str] = "product_pieces"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("piece", ASCENDING)], unique=True),
        IndexModel([("i_code", ASCENDING)]),
        IndexModel([("item_name", ASCENDING)]),
        IndexModel([("bill", ASCENDING)]),
        IndexModel([("main_key", ASCENDING)]),
        IndexModel([("dealer_code", ASCENDING)]),
        IndexModel([("dealer_name", ASCENDING)]),
        IndexModel([("distributor_code", ASCENDING)]),
        IndexModel([("distributor_name", ASCENDING)]),
        IndexModel([("category", ASCENDING)]),
        IndexModel([("product_type", ASCENDING)]),
        IndexModel([("piece", TEXT), ("item_name", TEXT)], name="piece_item_text"),
    ]

    piece: str = Field(..., min_length=1, max_length=120)
    i_code: str = Field(..., min_length=1, max_length=120)
    item_name: str = Field(..., min_length=1, max_length=250)
    product_type: str = Field("", max_length=120)
    category: str = Field("", max_length=120)
    size: str = Field("", max_length=120)
    describe: Optional[str] = None
    bill: str = Field(..., min_length=1, max_length=120)
    bill_date: datetime
    main_key: str = Field(..., min_length=1, max_length=160)
    has_booksale_match: bool
    distributor_code: Optional[Union[int, str]] = None
    distributor_name: str = ""
    distributor_add1: str = ""
    distributor_add2: str = ""
    distributor_city: str = ""
    dealer_code: Optional[Union[int, str]] = None
    dealer_name: str = ""
    dealer_add1: str = ""
    dealer_add2: str = ""
    dealer_city: str = ""
    dealer_state: str = ""
    dealer_phone: str = ""
    created_at: datetime
    updated_at: datetime

    _normalize_strings = field_validator(
        "piece",
        "i_code",
        "item_name",
        "product_type",
        "category",
        "size",
        "describe",
        "bill",
        "main_key",
        "distributor_name",
        "distributor_add1",
        "distributor_add2",
        "distributor_city",
        "dealer_name",
        "dealer_add1",
        "dealer_add2",
        "dealer_city",
        "dealer_state",
        "dealer_phone",
        mode="before",
    )(normalize_string_value)


class RegisteredProductDocument(IndexedDocument):
    collection_name: ClassVar[str] = "registered_products"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("piece", ASCENDING)], unique=True),
        IndexModel([("piece_id", ASCENDING)]),
        IndexModel([("customer_id", ASCENDING)]),
        IndexModel([("customer_email", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("registered_at", ASCENDING)]),
        IndexModel([("warranty_end", ASCENDING)]),
        IndexModel([("dealer_bill_number", ASCENDING)]),
        IndexModel([("dealer_bill_date", ASCENDING)]),
    ]

    customer_id: ObjectId
    customer_email: EmailStr
    piece_id: ObjectId
    piece: str = Field(..., min_length=1, max_length=120)
    item_name: str = Field(..., min_length=1, max_length=250)
    i_code: str = Field(..., min_length=1, max_length=120)
    category: str = Field(..., min_length=1, max_length=120)
    dealer_bill_number: str = Field("", max_length=120)
    dealer_bill_date: Optional[datetime] = None
    warranty_rule_id: Optional[ObjectId] = None
    warranty_start: datetime
    warranty_end: datetime
    warranty_months: int = Field(..., ge=1, le=600)
    status: WarrantyStatus
    registered_at: datetime

    _normalize_strings = field_validator(
        "piece", "item_name", "i_code", "category", "dealer_bill_number", mode="before"
    )(normalize_string_value)
    _normalize_email = field_validator("customer_email", mode="before")(normalize_email_value)
    _validate_customer_id = field_validator("customer_id", mode="before")(validate_required_object_id)
    _validate_piece_id = field_validator("piece_id", mode="before")(validate_required_object_id)
    _validate_rule_id = field_validator("warranty_rule_id", mode="before")(
        validate_optional_object_id
    )

    @model_validator(mode="after")
    def validate_warranty_dates(self):
        if self.warranty_end < self.warranty_start:
            raise ValueError("warranty_end must be greater than or equal to warranty_start")
        return self


class RegistrationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"


class RegistrationRequestDocument(IndexedDocument):
    collection_name: ClassVar[str] = "registration_requests"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("piece", ASCENDING)]),
        IndexModel([("customer_id", ASCENDING)]),
        IndexModel([("customer_email", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("requested_at", ASCENDING)]),
        IndexModel([("status", ASCENDING), ("requested_at", ASCENDING)]),
        IndexModel([("dealer_bill_number", ASCENDING)]),
        IndexModel([("dealer_bill_date", ASCENDING)]),
    ]

    customer_id: ObjectId
    customer_email: EmailStr
    piece_id: ObjectId
    piece: str = Field(..., min_length=1, max_length=120)
    item_name: str = Field(..., min_length=1, max_length=250)
    i_code: str = Field(..., min_length=1, max_length=120)
    category: str = Field(..., min_length=1, max_length=120)
    size: str = Field("", max_length=120)
    bill: str = ""
    bill_date: datetime
    dealer_bill_number: str = Field("", max_length=120)
    dealer_bill_date: Optional[datetime] = None
    warranty_rule_id: Optional[ObjectId] = None
    warranty_months: int = Field(..., ge=1, le=600)
    status: RegistrationStatus = RegistrationStatus.PENDING
    decline_reason: Optional[str] = Field(None, max_length=1000)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    requested_at: datetime
    feedback_required: bool = False
    feedback_submitted: bool = False

    _normalize_strings = field_validator(
        "piece", "item_name", "i_code", "category", "size", "bill", "dealer_bill_number", mode="before"
    )(normalize_string_value)
    _normalize_email = field_validator("customer_email", mode="before")(normalize_email_value)
    _validate_customer_id = field_validator("customer_id", mode="before")(validate_required_object_id)
    _validate_piece_id = field_validator("piece_id", mode="before")(validate_required_object_id)
    _validate_rule_id = field_validator("warranty_rule_id", mode="before")(
        validate_optional_object_id
    )


class WarrantyRuleDocument(IndexedDocument):
    collection_name: ClassVar[str] = "warranty_rules"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("category", ASCENDING)]),
        IndexModel([("category", ASCENDING), ("is_active", ASCENDING)]),
    ]

    category: str = Field(..., min_length=1, max_length=120)
    warranty_months: int = Field(..., ge=1, le=600)
    is_active: bool = True
    terms: List[str] = Field(default_factory=list)
    messages: Optional[Dict[str, str]] = None
    created_at: datetime
    updated_at: datetime

    _normalize_category = field_validator("category", mode="before")(normalize_string_value)

    @field_validator("terms")
    @classmethod
    def validate_terms(cls, value: List[str]) -> List[str]:
        cleaned = [t.strip() for t in value if t and t.strip()]
        if len(cleaned) > MAX_WARRANTY_TERMS:
            raise ValueError(f"Maximum {MAX_WARRANTY_TERMS} warranty terms allowed")
        return cleaned


class EnquiryDocument(IndexedDocument):
    collection_name: ClassVar[str] = "enquiries"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("piece", ASCENDING)]),
        IndexModel([("customer_id", ASCENDING)]),
        IndexModel([("customer_email", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("created_at", ASCENDING)]),
        IndexModel([("piece", ASCENDING), ("customer_email", ASCENDING)]),
    ]

    customer_id: ObjectId
    customer_email: EmailStr
    piece: str = Field(..., min_length=1, max_length=120)
    item_name: str = Field(..., min_length=1, max_length=250)
    issue_type: IssueType
    description: str = Field(..., min_length=1, max_length=5000)
    status: EnquiryStatus = EnquiryStatus.PENDING
    admin_note: Optional[str] = Field(None, max_length=5000)
    created_at: datetime
    updated_at: datetime

    _normalize_strings = field_validator(
        "piece", "item_name", "description", "admin_note", mode="before"
    )(normalize_string_value)
    _normalize_email = field_validator("customer_email", mode="before")(normalize_email_value)
    _validate_customer_id = field_validator("customer_id", mode="before")(validate_required_object_id)


class SupportContactDocument(IndexedDocument):
    collection_name: ClassVar[str] = "support_contacts"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("is_active", ASCENDING)]),
        IndexModel([("created_at", ASCENDING)]),
    ]

    name: str = Field(..., min_length=1, max_length=120)
    title: str = ""
    phone: str = ""
    email: str = ""
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    _normalize_strings = field_validator(
        "name", "title", "phone", mode="before"
    )(normalize_string_value)
    _normalize_email = field_validator("email", mode="before")(normalize_email_value)


class ImportBatchDocument(IndexedDocument):
    collection_name: ClassVar[str] = "import_batches"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("uploaded_at", ASCENDING)]),
        IndexModel([("uploaded_by", ASCENDING)]),
        IndexModel([("source", ASCENDING)]),
    ]

    uploaded_by: str = Field(..., min_length=1, max_length=250)
    uploaded_at: datetime
    booksale_rows: int = Field(..., ge=0)
    serials_rows: int = Field(..., ge=0)
    pieces_inserted: int = Field(..., ge=0)
    pieces_updated: int = Field(..., ge=0)
    pieces_failed: int = Field(..., ge=0)
    failed_rows: List[Dict[str, Any]] = Field(default_factory=list)
    source: str = Field(..., min_length=1, max_length=120)

    _normalize_strings = field_validator("uploaded_by", "source", mode="before")(
        normalize_string_value
    )


class CustomerFeedbackDocument(IndexedDocument):
    collection_name: ClassVar[str] = "customer_feedbacks"
    indexes: ClassVar[List[IndexModel]] = [
        IndexModel([("customer_id", ASCENDING), ("piece", ASCENDING)], unique=True),
        IndexModel([("piece", ASCENDING)]),
        IndexModel([("customer_email", ASCENDING)]),
        IndexModel([("submitted_at", ASCENDING)]),
    ]

    customer_id: ObjectId
    customer_email: EmailStr
    customer_name: str = ""
    piece: str = Field(..., min_length=1, max_length=120)
    item_name: str = ""
    dealer_name: str = ""
    answers: Dict[str, Any]
    submitted_at: datetime

    _normalize_strings = field_validator("customer_name", "piece", "item_name", "dealer_name", mode="before")(normalize_string_value)
    _normalize_email = field_validator("customer_email", mode="before")(normalize_email_value)
    _validate_customer_id = field_validator("customer_id", mode="before")(validate_required_object_id)


DOCUMENT_MODELS = [
    CustomerDocument,
    AdminUserDocument,
    OTPSessionDocument,
    ProductPieceDocument,
    RegistrationRequestDocument,
    RegisteredProductDocument,
    WarrantyRuleDocument,
    EnquiryDocument,
    SupportContactDocument,
    ImportBatchDocument,
    CustomerFeedbackDocument,
]


COLLECTION_INDEXES: Dict[str, List[IndexModel]] = {
    model.collection_name: model.indexes for model in DOCUMENT_MODELS
}
