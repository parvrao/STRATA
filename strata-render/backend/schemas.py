"""
Pydantic v2 schemas — request validation + response serialisation.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Any, Dict
from datetime import datetime
from models import PlanEnum, StageEnum, AnalysisTypeEnum, BookingStatusEnum, ServiceTypeEnum, SubStatusEnum


# ── Shared ────────────────────────────────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


class PaginatedResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)
    company_name: Optional[str] = Field(None, max_length=200)
    job_title: Optional[str] = Field(None, max_length=200)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int                    # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


# ── Users ─────────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    company_name: Optional[str]
    job_title: Optional[str]
    plan: PlanEnum
    is_active: bool
    is_verified: bool
    avatar_url: Optional[str]
    preferred_stage: Optional[StageEnum]
    tokens_used_month: int
    created_at: datetime
    last_login_at: Optional[datetime]

    model_config = {"from_attributes": True}


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = Field(None, max_length=200)
    company_name: Optional[str] = Field(None, max_length=200)
    job_title: Optional[str] = Field(None, max_length=200)
    preferred_stage: Optional[StageEnum] = None


# ── Analyses ──────────────────────────────────────────────────────────────────

class CreateAnalysisRequest(BaseModel):
    stage: StageEnum
    analysis_type: AnalysisTypeEnum
    title: str = Field(max_length=500)
    input_data: Dict[str, Any]
    tags: Optional[List[str]] = []


class AnalysisResponse(BaseModel):
    id: str
    stage: StageEnum
    analysis_type: AnalysisTypeEnum
    title: str
    input_data: Dict[str, Any]
    output_data: Optional[Dict[str, Any]]
    tokens_used: int
    status: str
    is_starred: bool
    tags: List[str]
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AnalysisListResponse(PaginatedResponse):
    items: List[AnalysisResponse]


class UpdateAnalysisRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    is_starred: Optional[bool] = None
    tags: Optional[List[str]] = None


# ── AI Requests ───────────────────────────────────────────────────────────────

class CustomerIntelRequest(BaseModel):
    stage: StageEnum
    product_description: str = Field(min_length=10, max_length=2000)
    industry: str = Field(max_length=200)
    price_point: Optional[str] = None
    target_customer: Optional[str] = Field(None, max_length=1000)
    geography: Optional[str] = None
    # Stage-specific extras
    arr: Optional[str] = None               # growth
    acv: Optional[str] = None               # growth
    deal_size: Optional[str] = None         # enterprise
    sales_cycle: Optional[str] = None       # enterprise


class ProductProfilerRequest(BaseModel):
    stage: StageEnum
    product_name: str = Field(max_length=200)
    features: str = Field(max_length=2000)
    description: str = Field(max_length=2000)
    competitors: Optional[str] = Field(None, max_length=500)
    price_tier: Optional[str] = None
    # Enterprise extras
    compliance_certs: Optional[str] = None
    integrations: Optional[str] = None


class PositioningRequest(BaseModel):
    stage: StageEnum
    current_positioning: str = Field(max_length=1000)
    brand_values: str = Field(max_length=300)
    competitors: str = Field(max_length=1000)
    feel: Optional[str] = Field(None, max_length=300)
    positioning_axis: Optional[str] = None
    differentiation: Optional[str] = None
    threat: Optional[str] = Field(None, max_length=500)
    drift_markets: Optional[str] = Field(None, max_length=500)


class IntakeAnalysisRequest(BaseModel):
    stage: StageEnum
    analysis_type: AnalysisTypeEnum
    data: Dict[str, Any]


class AIResponse(BaseModel):
    result: Dict[str, Any]
    tokens_used: int
    analysis_id: Optional[str] = None   # saved to DB


# ── Billing ───────────────────────────────────────────────────────────────────

class CreateCheckoutRequest(BaseModel):
    plan: PlanEnum
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class PortalResponse(BaseModel):
    portal_url: str


class SubscriptionResponse(BaseModel):
    id: str
    plan: PlanEnum
    status: SubStatusEnum
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    trial_end: Optional[datetime]

    model_config = {"from_attributes": True}


class PlanLimitsResponse(BaseModel):
    plan: PlanEnum
    monthly_token_budget: int
    tokens_used: int
    tokens_remaining: int
    analyses_this_month: int
    can_use_human_services: bool


# ── Booking ───────────────────────────────────────────────────────────────────

class ExpertResponse(BaseModel):
    id: str
    name: str
    title: str
    bio: str
    avatar_url: Optional[str]
    specialties: List[str]
    stages: List[str]
    rating: float
    sessions_count: int
    is_available: bool
    price_per_hour: Optional[int]

    model_config = {"from_attributes": True}


class CreateBookingRequest(BaseModel):
    expert_id: str
    service_type: ServiceTypeEnum
    scheduled_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=1000)
    analysis_id: Optional[str] = None


class BookingResponse(BaseModel):
    id: str
    expert_id: Optional[str]
    service_type: ServiceTypeEnum
    status: BookingStatusEnum
    scheduled_at: Optional[datetime]
    duration_minutes: int
    price_cents: int
    currency: str
    notes: Optional[str]
    meeting_url: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class BookingDetailResponse(BookingResponse):
    expert: Optional[ExpertResponse]
    user_id: str

    model_config = {"from_attributes": True}


# ── Admin ─────────────────────────────────────────────────────────────────────

class AdminUserResponse(UserResponse):
    is_admin: bool
    tokens_used_month: int

    model_config = {"from_attributes": True}


class AdminUserListResponse(PaginatedResponse):
    items: List[AdminUserResponse]


class AdminStatsResponse(BaseModel):
    total_users: int
    active_subscriptions: int
    mrr_cents: int
    analyses_today: int
    analyses_this_month: int
    tokens_used_today: int
    bookings_pending: int
    top_plans: Dict[str, int]


class AdminUpdateUserRequest(BaseModel):
    plan: Optional[PlanEnum] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


# ── Notifications ─────────────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    body: Optional[str]
    read: bool
    data: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}
