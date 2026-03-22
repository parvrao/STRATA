"""
Auth routes — register, login, refresh, logout, password reset, email verify.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from datetime import datetime, timedelta, timezone
import secrets

from database import get_db
from models import User, RefreshToken, PasswordResetToken, EmailVerificationToken
from schemas import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest,
    ForgotPasswordRequest, ResetPasswordRequest, ChangePasswordRequest,
    UserResponse, MessageResponse
)
from auth_utils import (
    hash_password, verify_password, hash_token,
    create_access_token, create_refresh_token,
    get_user_by_email, get_user_by_id, get_current_user
)
from middleware.rate_limit import auth_limit, strict_limit
from config import settings
from services.email import send_verification_email, send_password_reset_email

router = APIRouter()


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    body: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(auth_limit),
):
    existing = await get_user_by_email(body.email, db)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email.lower().strip(),
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        company_name=body.company_name,
        job_title=body.job_title,
    )
    db.add(user)
    await db.flush()   # get user.id before commit

    # Email verification token
    raw_token = secrets.token_urlsafe(32)
    ev = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db.add(ev)
    await db.commit()
    await db.refresh(user)

    # Send verification email in background
    background_tasks.add_task(send_verification_email, user.email, user.full_name, raw_token)

    # Issue tokens
    access = create_access_token(user.id)
    refresh_raw = create_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(rt)
    await db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh_raw,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _=Depends(auth_limit),
):
    user = await get_user_by_email(body.email.lower(), db)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account suspended")

    # Rotate refresh token — delete old ones for this device (simple single-device approach)
    user.last_login_at = datetime.now(timezone.utc)

    access = create_access_token(user.id, {"plan": user.plan.value})
    refresh_raw = create_refresh_token()
    rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        user_agent=request.headers.get("User-Agent", "")[:512],
        ip_address=request.client.host if request.client else None,
    )
    db.add(rt)
    await db.commit()

    return TokenResponse(
        access_token=access,
        refresh_token=refresh_raw,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(auth_limit),
):
    token_hash = hash_token(body.refresh_token)
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .where(RefreshToken.revoked == False)
    )
    rt = result.scalar_one_or_none()

    if not rt or rt.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = await get_user_by_id(rt.user_id, db)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Revoke old, issue new (rotation)
    rt.revoked = True
    new_access = create_access_token(user.id, {"plan": user.plan.value})
    new_refresh_raw = create_refresh_token()
    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_refresh_raw),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(new_rt)
    await db.commit()

    return TokenResponse(
        access_token=new_access,
        refresh_token=new_refresh_raw,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout", response_model=MessageResponse)
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token_hash = hash_token(body.refresh_token)
    await db.execute(
        delete(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .where(RefreshToken.user_id == current_user.id)
    )
    await db.commit()
    return MessageResponse(message="Logged out successfully")


# ── Me ────────────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed = {"full_name", "company_name", "job_title", "preferred_stage"}
    for field, val in body.items():
        if field in allowed and val is not None:
            setattr(current_user, field, val)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(strict_limit),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(body.new_password)
    # Revoke all refresh tokens
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == current_user.id))
    await db.commit()
    return MessageResponse(message="Password changed. Please log in again.")


# ── Email Verification ────────────────────────────────────────────────────────

@router.get("/verify-email/{token}", response_model=MessageResponse)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    token_hash = hash_token(token)
    result = await db.execute(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash == token_hash)
        .where(EmailVerificationToken.used == False)
    )
    ev = result.scalar_one_or_none()
    if not ev or ev.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    ev.used = True
    user = await get_user_by_id(ev.user_id, db)
    if user:
        user.is_verified = True
    await db.commit()
    return MessageResponse(message="Email verified successfully")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _=Depends(strict_limit),
):
    if current_user.is_verified:
        raise HTTPException(status_code=400, detail="Email already verified")
    raw_token = secrets.token_urlsafe(32)
    ev = EmailVerificationToken(
        user_id=current_user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db.add(ev)
    await db.commit()
    background_tasks.add_task(send_verification_email, current_user.email, current_user.full_name, raw_token)
    return MessageResponse(message="Verification email sent")


# ── Password Reset ────────────────────────────────────────────────────────────

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _=Depends(strict_limit),
):
    user = await get_user_by_email(body.email.lower(), db)
    # Always return 200 — don't leak whether email exists
    if user and user.is_active:
        raw_token = secrets.token_urlsafe(32)
        prt = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(prt)
        await db.commit()
        background_tasks.add_task(send_password_reset_email, user.email, user.full_name, raw_token)
    return MessageResponse(message="If an account with that email exists, a reset link has been sent.")


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(strict_limit),
):
    token_hash = hash_token(body.token)
    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .where(PasswordResetToken.used == False)
    )
    prt = result.scalar_one_or_none()
    if not prt or prt.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    prt.used = True
    user = await get_user_by_id(prt.user_id, db)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.hashed_password = hash_password(body.new_password)
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await db.commit()
    return MessageResponse(message="Password reset successfully. Please log in.")
