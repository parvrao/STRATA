"""
Database models — all tables defined here.
Run `alembic revision --autogenerate` after changes.
"""

from sqlalchemy import (
    Column, String, Integer, Boolean, Text, Float,
    DateTime, ForeignKey, Enum, JSON, BigInteger, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import uuid
import enum


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ─────────────────────────────────────────────────────────────────────

class PlanEnum(str, enum.Enum):
    free        = "free"
    build       = "build"
    fundraise   = "fundraise"
    growth      = "growth"
    scale_plus  = "scale_plus"
    enterprise  = "enterprise"
    command     = "command"

class StageEnum(str, enum.Enum):
    startup    = "startup"
    growth     = "growth"
    enterprise = "enterprise"

class AnalysisTypeEnum(str, enum.Enum):
    customer_intel = "customer_intel"
    product_profiler = "product_profiler"
    positioning_suite = "positioning_suite"
    pmf_analysis = "pmf_analysis"
    gtm_playbook = "gtm_playbook"
    board_brief = "board_brief"

class BookingStatusEnum(str, enum.Enum):
    pending   = "pending"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"

class SubStatusEnum(str, enum.Enum):
    active            = "active"
    past_due          = "past_due"
    cancelled         = "cancelled"
    trialing          = "trialing"
    incomplete        = "incomplete"

class ServiceTypeEnum(str, enum.Enum):
    strategy_deep_dive      = "strategy_deep_dive"
    board_deck_review       = "board_deck_review"
    fractional_partner      = "fractional_partner"
    enterprise_engagement   = "enterprise_engagement"


# ── Users ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id              = Column(String(36), primary_key=True, default=gen_uuid)
    email           = Column(String(320), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    full_name       = Column(String(200), nullable=False)
    company_name    = Column(String(200), nullable=True)
    job_title       = Column(String(200), nullable=True)
    plan            = Column(Enum(PlanEnum), default=PlanEnum.free, nullable=False)
    is_active       = Column(Boolean, default=True, nullable=False)
    is_verified     = Column(Boolean, default=False, nullable=False)
    is_admin        = Column(Boolean, default=False, nullable=False)
    avatar_url      = Column(String(512), nullable=True)
    preferred_stage = Column(Enum(StageEnum), nullable=True)
    # Usage tracking
    tokens_used_month = Column(BigInteger, default=0, nullable=False)
    usage_reset_at    = Column(DateTime(timezone=True), server_default=func.now())
    # Timestamps
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
    last_login_at   = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    refresh_tokens  = relationship("RefreshToken",   back_populates="user", cascade="all, delete-orphan")
    analyses        = relationship("Analysis",        back_populates="user", cascade="all, delete-orphan")
    subscription    = relationship("Subscription",    back_populates="user", uselist=False, cascade="all, delete-orphan")
    bookings        = relationship("Booking",         back_populates="user", cascade="all, delete-orphan")
    usage_logs      = relationship("UsageLog",        back_populates="user", cascade="all, delete-orphan")
    notifications   = relationship("Notification",   back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id         = Column(String(36), primary_key=True, default=gen_uuid)
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(256), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked    = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user_agent = Column(String(512), nullable=True)
    ip_address = Column(String(45), nullable=True)

    user = relationship("User", back_populates="refresh_tokens")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id         = Column(String(36), primary_key=True, default=gen_uuid)
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(256), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used       = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id         = Column(String(36), primary_key=True, default=gen_uuid)
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(256), unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used       = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Analyses ──────────────────────────────────────────────────────────────────

class Analysis(Base):
    __tablename__ = "analyses"

    id            = Column(String(36), primary_key=True, default=gen_uuid)
    user_id       = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    stage         = Column(Enum(StageEnum), nullable=False)
    analysis_type = Column(Enum(AnalysisTypeEnum), nullable=False)
    title         = Column(String(500), nullable=False)
    input_data    = Column(JSON, nullable=False)     # raw user input
    output_data   = Column(JSON, nullable=True)     # AI-generated results
    tokens_used   = Column(Integer, default=0)
    status        = Column(String(20), default="completed")  # pending | completed | failed
    is_starred    = Column(Boolean, default=False)
    tags          = Column(JSON, default=list)       # ["series-a", "saas", ...]
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="analyses")

    __table_args__ = (
        Index("ix_analyses_user_stage",  "user_id", "stage"),
        Index("ix_analyses_user_type",   "user_id", "analysis_type"),
        Index("ix_analyses_user_created","user_id", "created_at"),
    )


# ── Subscriptions / Billing ───────────────────────────────────────────────────

class Subscription(Base):
    __tablename__ = "subscriptions"

    id                      = Column(String(36), primary_key=True, default=gen_uuid)
    user_id                 = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    stripe_customer_id      = Column(String(64), unique=True, nullable=True, index=True)
    stripe_subscription_id  = Column(String(64), unique=True, nullable=True, index=True)
    stripe_price_id         = Column(String(64), nullable=True)
    plan                    = Column(Enum(PlanEnum), nullable=False)
    status                  = Column(Enum(SubStatusEnum), default=SubStatusEnum.active)
    current_period_start    = Column(DateTime(timezone=True), nullable=True)
    current_period_end      = Column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end    = Column(Boolean, default=False)
    trial_end               = Column(DateTime(timezone=True), nullable=True)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())
    updated_at              = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="subscription")


class PaymentEvent(Base):
    """Raw Stripe webhook events — audit log."""
    __tablename__ = "payment_events"

    id             = Column(String(36), primary_key=True, default=gen_uuid)
    stripe_event_id = Column(String(64), unique=True, nullable=False)
    event_type     = Column(String(100), nullable=False)
    user_id        = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    amount_cents   = Column(Integer, nullable=True)
    currency       = Column(String(3), nullable=True)
    payload        = Column(JSON, nullable=False)
    processed      = Column(Boolean, default=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())


# ── Experts ───────────────────────────────────────────────────────────────────

class Expert(Base):
    __tablename__ = "experts"

    id              = Column(String(36), primary_key=True, default=gen_uuid)
    name            = Column(String(200), nullable=False)
    title           = Column(String(300), nullable=False)
    bio             = Column(Text, nullable=False)
    avatar_url      = Column(String(512), nullable=True)
    specialties     = Column(JSON, default=list)      # ["GTM", "Series A-C", "APAC"]
    stages          = Column(JSON, default=list)      # ["startup", "growth"]
    rating          = Column(Float, default=5.0)
    sessions_count  = Column(Integer, default=0)
    calcom_username = Column(String(100), nullable=True)  # for cal.com integration
    is_available    = Column(Boolean, default=True)
    price_per_hour  = Column(Integer, nullable=True)  # cents
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    bookings = relationship("Booking", back_populates="expert")


# ── Bookings ──────────────────────────────────────────────────────────────────

class Booking(Base):
    __tablename__ = "bookings"

    id                  = Column(String(36), primary_key=True, default=gen_uuid)
    user_id             = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expert_id           = Column(String(36), ForeignKey("experts.id", ondelete="SET NULL"), nullable=True)
    service_type        = Column(Enum(ServiceTypeEnum), nullable=False)
    status              = Column(Enum(BookingStatusEnum), default=BookingStatusEnum.pending)
    scheduled_at        = Column(DateTime(timezone=True), nullable=True)
    duration_minutes    = Column(Integer, default=60)
    price_cents         = Column(Integer, nullable=False)
    currency            = Column(String(3), default="USD")
    stripe_payment_intent_id = Column(String(64), nullable=True)
    notes               = Column(Text, nullable=True)            # from user
    meeting_url         = Column(String(512), nullable=True)     # Zoom / Meet link
    calcom_booking_id   = Column(String(100), nullable=True)
    analysis_id         = Column(String(36), ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True)
    reminder_sent       = Column(Boolean, default=False)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())

    user   = relationship("User",   back_populates="bookings")
    expert = relationship("Expert", back_populates="bookings")

    __table_args__ = (
        Index("ix_bookings_user_status", "user_id", "status"),
    )


# ── Usage Logs ────────────────────────────────────────────────────────────────

class UsageLog(Base):
    __tablename__ = "usage_logs"

    id            = Column(String(36), primary_key=True, default=gen_uuid)
    user_id       = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint      = Column(String(200), nullable=False)
    analysis_type = Column(String(100), nullable=True)
    stage         = Column(String(50), nullable=True)
    tokens_input  = Column(Integer, default=0)
    tokens_output = Column(Integer, default=0)
    tokens_total  = Column(Integer, default=0)
    latency_ms    = Column(Integer, nullable=True)
    model         = Column(String(100), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    user = relationship("User", back_populates="usage_logs")

    __table_args__ = (
        Index("ix_usage_user_date", "user_id", "created_at"),
    )


# ── Notifications ─────────────────────────────────────────────────────────────

class Notification(Base):
    __tablename__ = "notifications"

    id         = Column(String(36), primary_key=True, default=gen_uuid)
    user_id    = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type       = Column(String(50), nullable=False)   # booking_confirmed | analysis_ready | payment_failed
    title      = Column(String(300), nullable=False)
    body       = Column(Text, nullable=True)
    read       = Column(Boolean, default=False)
    data       = Column(JSON, nullable=True)          # extra context
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")
