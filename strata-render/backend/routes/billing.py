"""
Billing routes — demo stub.
Returns helpful messages instead of crashing when Stripe isn't configured.
"""

from fastapi import APIRouter, Depends, Request, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import User, Subscription, PlanEnum, SubStatusEnum
from schemas import SubscriptionResponse, PlanLimitsResponse
from auth_utils import get_current_user
from config import settings

router = APIRouter()

PLAN_PRICES_CENTS = {
    PlanEnum.free: 0, PlanEnum.build: 4900, PlanEnum.fundraise: 14900,
    PlanEnum.growth: 19900, PlanEnum.scale_plus: 39900,
    PlanEnum.enterprise: 59900, PlanEnum.command: 129900,
}

def stripe_enabled():
    return bool(settings.STRIPE_SECRET_KEY)


@router.post("/checkout")
async def create_checkout(body: dict, current_user: User = Depends(get_current_user)):
    if not stripe_enabled():
        return {"message": "Stripe not configured in this demo. Add STRIPE_SECRET_KEY to enable payments.", "demo": True}
    raise HTTPException(status_code=501, detail="Configure STRIPE_SECRET_KEY to enable checkout")


@router.post("/portal")
async def create_portal(body: dict, current_user: User = Depends(get_current_user)):
    if not stripe_enabled():
        return {"message": "Stripe not configured in this demo.", "demo": True}
    raise HTTPException(status_code=501, detail="Configure STRIPE_SECRET_KEY to enable billing portal")


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Subscription).where(Subscription.user_id == current_user.id))
    sub = result.scalar_one_or_none()
    if not sub:
        return SubscriptionResponse(
            id="demo", plan=PlanEnum.free, status=SubStatusEnum.active,
            current_period_end=None, cancel_at_period_end=False, trial_end=None,
        )
    return sub


@router.get("/limits", response_model=PlanLimitsResponse)
async def get_plan_limits(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from routes.ai import PLAN_LIMITS
    from sqlalchemy import func
    from models import Analysis
    from datetime import datetime, timezone

    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count_result = await db.execute(
        select(func.count()).where(
            Analysis.user_id == current_user.id,
            Analysis.created_at >= month_start
        )
    )
    analyses_count = count_result.scalar_one()
    limit = PLAN_LIMITS.get(current_user.plan, settings.FREE_TIER_MONTHLY_TOKENS)
    return PlanLimitsResponse(
        plan=current_user.plan,
        monthly_token_budget=limit,
        tokens_used=current_user.tokens_used_month,
        tokens_remaining=max(0, limit - current_user.tokens_used_month),
        analyses_this_month=analyses_count,
        can_use_human_services=True,  # always true for demo
    )


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, stripe_signature: str = Header(None, alias="Stripe-Signature")):
    if not stripe_enabled():
        return {"status": "stripe_not_configured"}
    return {"status": "ok"}
