"""
Booking routes — demo version (no Stripe payment required).
Bookings work but checkout is skipped.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from database import get_db
from models import User, Expert, Booking, Notification, BookingStatusEnum, ServiceTypeEnum
from schemas import ExpertResponse, CreateBookingRequest, BookingResponse, BookingDetailResponse, MessageResponse, NotificationResponse
from auth_utils import get_current_user, get_current_verified_user
from services.email import send_booking_confirmation_email

router = APIRouter()

SERVICE_PRICES_CENTS = {
    ServiceTypeEnum.strategy_deep_dive: 29900,
    ServiceTypeEnum.board_deck_review: 79900,
    ServiceTypeEnum.fractional_partner: 240000,
    ServiceTypeEnum.enterprise_engagement: 0,
}


@router.get("/experts", response_model=list[ExpertResponse])
async def list_experts(
    stage: Optional[str] = Query(None),
    available_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    query = select(Expert)
    if available_only:
        query = query.where(Expert.is_available == True)
    result = await db.execute(query.order_by(Expert.rating.desc()))
    experts = result.scalars().all()
    if stage:
        experts = [e for e in experts if stage in e.stages]
    return experts


@router.get("/experts/{expert_id}", response_model=ExpertResponse)
async def get_expert(expert_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Expert).where(Expert.id == expert_id))
    expert = result.scalar_one_or_none()
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")
    return expert


@router.post("/", response_model=BookingResponse, status_code=201)
async def create_booking(
    body: CreateBookingRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_verified_user),
):
    result = await db.execute(select(Expert).where(Expert.id == body.expert_id))
    expert = result.scalar_one_or_none()
    if not expert:
        raise HTTPException(status_code=404, detail="Expert not found")

    price = SERVICE_PRICES_CENTS.get(body.service_type, 0)
    booking = Booking(
        user_id=current_user.id, expert_id=body.expert_id,
        service_type=body.service_type, status=BookingStatusEnum.pending,
        scheduled_at=body.scheduled_at, price_cents=price, currency="USD",
        notes=body.notes, analysis_id=body.analysis_id,
    )
    db.add(booking)
    await db.flush()

    background_tasks.add_task(
        send_booking_confirmation_email,
        current_user.email, current_user.full_name,
        expert.name, body.service_type.value,
        body.scheduled_at, booking.id,
    )
    notif = Notification(
        user_id=current_user.id, type="booking_created",
        title="Booking Request Received",
        body=f"Your session with {expert.name} is being confirmed.",
        data={"booking_id": booking.id},
    )
    db.add(notif)
    await db.commit()
    await db.refresh(booking)
    return booking


@router.get("/", response_model=list[BookingDetailResponse])
async def list_my_bookings(
    status: Optional[BookingStatusEnum] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Booking).where(Booking.user_id == current_user.id)
    if status:
        query = query.where(Booking.status == status)
    result = await db.execute(query.order_by(Booking.created_at.desc()))
    return result.scalars().all()


@router.get("/{booking_id}", response_model=BookingDetailResponse)
async def get_booking(
    booking_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.user_id == current_user.id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.post("/{booking_id}/cancel", response_model=MessageResponse)
async def cancel_booking(
    booking_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.user_id == current_user.id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status in (BookingStatusEnum.completed, BookingStatusEnum.cancelled):
        raise HTTPException(status_code=400, detail=f"Cannot cancel a {booking.status.value} booking")
    booking.status = BookingStatusEnum.cancelled
    await db.commit()
    return MessageResponse(message="Booking cancelled")


@router.post("/{booking_id}/checkout")
async def booking_checkout(booking_id: str, body: dict, current_user: User = Depends(get_current_user)):
    return {"message": "Demo mode — payment processing not enabled.", "demo": True, "booking_id": booking_id}


@router.get("/notifications/all", response_model=list[NotificationResponse])
async def get_notifications(
    unread_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Notification).where(Notification.user_id == current_user.id)
    if unread_only:
        query = query.where(Notification.read == False)
    result = await db.execute(query.order_by(Notification.created_at.desc()).limit(50))
    return result.scalars().all()


@router.post("/notifications/{notif_id}/read", response_model=MessageResponse)
async def mark_read(
    notif_id: str, db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(Notification.id == notif_id, Notification.user_id == current_user.id)
    )
    notif = result.scalar_one_or_none()
    if notif:
        notif.read = True
        await db.commit()
    return MessageResponse(message="Marked as read")


@router.post("/notifications/read-all", response_model=MessageResponse)
async def mark_all_read(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification).where(Notification.user_id == current_user.id, Notification.read == False)
    )
    for n in result.scalars().all():
        n.read = True
    await db.commit()
    return MessageResponse(message="All read")
