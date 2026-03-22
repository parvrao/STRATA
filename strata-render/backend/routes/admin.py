"""
Admin routes — user management, revenue analytics, usage overview.
Requires is_admin=True on the user record.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

from database import get_db
from models import User, Subscription, Analysis, UsageLog, Booking, BookingStatusEnum, PlanEnum, SubStatusEnum
from schemas import (
    AdminUserResponse, AdminUserListResponse, AdminStatsResponse,
    AdminUpdateUserRequest, MessageResponse
)
from auth_utils import get_admin_user
from routes.billing import PLAN_PRICES_CENTS

router = APIRouter()
logger = logging.getLogger("strata.admin")


# ── Dashboard stats ───────────────────────────────────────────────────────────

@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Total users
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()

    # Active subscriptions
    active_subs = (
        await db.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status.in_([SubStatusEnum.active, SubStatusEnum.trialing]))
        )
    ).scalar_one()

    # MRR
    subs_result = await db.execute(
        select(Subscription.plan)
        .where(Subscription.status.in_([SubStatusEnum.active, SubStatusEnum.trialing]))
    )
    plans = subs_result.scalars().all()
    mrr = sum(PLAN_PRICES_CENTS.get(p, 0) for p in plans)

    # Analyses today
    analyses_today = (
        await db.execute(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.created_at >= today_start)
        )
    ).scalar_one()

    # Analyses this month
    analyses_month = (
        await db.execute(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.created_at >= month_start)
        )
    ).scalar_one()

    # Tokens today
    tokens_today_result = await db.execute(
        select(func.sum(UsageLog.tokens_total))
        .where(UsageLog.created_at >= today_start)
    )
    tokens_today = tokens_today_result.scalar_one() or 0

    # Pending bookings
    pending_bookings = (
        await db.execute(
            select(func.count())
            .select_from(Booking)
            .where(Booking.status == BookingStatusEnum.pending)
        )
    ).scalar_one()

    # Plans distribution
    plan_dist_result = await db.execute(
        select(User.plan, func.count().label("count"))
        .group_by(User.plan)
    )
    top_plans = {row.plan.value: row.count for row in plan_dist_result.all()}

    return AdminStatsResponse(
        total_users=total_users,
        active_subscriptions=active_subs,
        mrr_cents=mrr,
        analyses_today=analyses_today,
        analyses_this_month=analyses_month,
        tokens_used_today=tokens_today,
        bookings_pending=pending_bookings,
        top_plans=top_plans,
    )


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, max_length=200),
    plan: Optional[PlanEnum] = None,
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    filters = []
    if search:
        filters.append(
            User.email.ilike(f"%{search}%") | User.full_name.ilike(f"%{search}%")
        )
    if plan:
        filters.append(User.plan == plan)
    if is_active is not None:
        filters.append(User.is_active == is_active)

    count_q = select(func.count()).select_from(User)
    if filters:
        from sqlalchemy import and_
        count_q = count_q.where(and_(*filters))
    total = (await db.execute(count_q)).scalar_one()

    query = select(User).order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    if filters:
        query = query.where(and_(*filters))
    users = (await db.execute(query)).scalars().all()

    return AdminUserListResponse(
        total=total, page=page, per_page=per_page,
        pages=-(-total // per_page), items=users
    )


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: str,
    body: AdminUpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.plan is not None:
        user.plan = body.plan
        logger.info(f"Admin {admin.email} changed user {user.email} plan to {body.plan}")
    if body.is_active is not None:
        user.is_active = body.is_active
        logger.info(f"Admin {admin.email} set user {user.email} is_active={body.is_active}")
    if body.is_admin is not None:
        user.is_admin = body.is_admin
        logger.info(f"Admin {admin.email} set user {user.email} is_admin={body.is_admin}")

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Soft-delete — sets is_active=False."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    user.is_active = False
    await db.commit()
    logger.info(f"Admin {admin.email} deactivated user {user.email}")
    return MessageResponse(message=f"User {user.email} deactivated")


# ── Usage analytics ───────────────────────────────────────────────────────────

@router.get("/analytics/usage")
async def get_usage_analytics(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Daily token usage and analysis counts for the last N days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Daily token usage
    daily_tokens = await db.execute(
        select(
            func.date_trunc("day", UsageLog.created_at).label("day"),
            func.sum(UsageLog.tokens_total).label("tokens"),
            func.count().label("calls"),
        )
        .where(UsageLog.created_at >= since)
        .group_by("day")
        .order_by("day")
    )

    # Analyses by type
    by_type = await db.execute(
        select(Analysis.analysis_type, func.count().label("count"))
        .where(Analysis.created_at >= since)
        .group_by(Analysis.analysis_type)
    )

    # Top users by tokens
    top_users = await db.execute(
        select(User.email, User.plan, func.sum(UsageLog.tokens_total).label("tokens"))
        .join(UsageLog, UsageLog.user_id == User.id)
        .where(UsageLog.created_at >= since)
        .group_by(User.email, User.plan)
        .order_by(func.sum(UsageLog.tokens_total).desc())
        .limit(20)
    )

    return {
        "daily": [
            {"day": str(r.day.date()), "tokens": r.tokens or 0, "calls": r.calls}
            for r in daily_tokens.all()
        ],
        "by_type": {r.analysis_type.value: r.count for r in by_type.all()},
        "top_users": [
            {"email": r.email, "plan": r.plan.value, "tokens": r.tokens or 0}
            for r in top_users.all()
        ],
    }


@router.get("/analytics/revenue")
async def get_revenue_analytics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """MRR breakdown, churn signals, subscription growth."""
    subs = (await db.execute(
        select(Subscription.plan, Subscription.status, func.count().label("count"))
        .group_by(Subscription.plan, Subscription.status)
    )).all()

    mrr_by_plan = {}
    for row in subs:
        if row.status in (SubStatusEnum.active, SubStatusEnum.trialing):
            mrr_by_plan[row.plan.value] = mrr_by_plan.get(row.plan.value, 0) + (
                PLAN_PRICES_CENTS.get(row.plan, 0) * row.count
            )

    # New subs last 30 days
    month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    new_subs = (await db.execute(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.created_at >= month_ago)
    )).scalar_one()

    cancelled = (await db.execute(
        select(func.count())
        .select_from(Subscription)
        .where(Subscription.status == SubStatusEnum.cancelled)
        .where(Subscription.updated_at >= month_ago)
    )).scalar_one()

    return {
        "mrr_by_plan_cents": mrr_by_plan,
        "total_mrr_cents": sum(mrr_by_plan.values()),
        "new_subscriptions_30d": new_subs,
        "cancellations_30d": cancelled,
        "subscription_breakdown": [
            {"plan": r.plan.value, "status": r.status.value, "count": r.count}
            for r in subs
        ],
    }


# ── Bookings admin ────────────────────────────────────────────────────────────

@router.get("/bookings")
async def list_all_bookings(
    status: Optional[BookingStatusEnum] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    query = select(Booking).order_by(Booking.created_at.desc())
    if status:
        query = query.where(Booking.status == status)
    total = (await db.execute(select(func.count()).select_from(Booking))).scalar_one()
    bookings = (await db.execute(query.offset((page - 1) * per_page).limit(per_page))).scalars().all()
    return {"total": total, "items": bookings}


@router.patch("/bookings/{booking_id}")
async def admin_update_booking(
    booking_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    result = await db.execute(select(Booking).where(Booking.id == booking_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if "status" in body:
        booking.status = BookingStatusEnum(body["status"])
    if "meeting_url" in body:
        booking.meeting_url = body["meeting_url"]
    if "scheduled_at" in body:
        booking.scheduled_at = body["scheduled_at"]

    # Send notification to user
    from models import Notification
    notif = Notification(
        user_id=booking.user_id,
        type=f"booking_{booking.status.value}",
        title=f"Booking {booking.status.value.title()}",
        body=f"Your session has been {booking.status.value}." + (
            f" Join here: {booking.meeting_url}" if booking.meeting_url else ""
        ),
        data={"booking_id": booking.id},
    )
    db.add(notif)
    await db.commit()

    logger.info(f"Admin {admin.email} updated booking {booking_id} → {booking.status}")
    return {"message": "Booking updated", "booking_id": booking_id}
