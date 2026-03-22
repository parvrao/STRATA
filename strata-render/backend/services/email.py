"""
Email service — demo stub.
Logs emails to console instead of sending them when Resend isn't configured.
"""
import logging
from typing import Optional
from datetime import datetime
from config import settings

logger = logging.getLogger("strata.email")


async def _send(to: str, subject: str, body_preview: str):
    if not settings.RESEND_API_KEY:
        logger.info(f"[DEMO EMAIL — not sent] To: {to} | Subject: {subject} | {body_preview[:80]}")
        return True
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}", "Content-Type": "application/json"},
                json={"from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
                      "to": [to], "subject": subject, "html": body_preview},
                timeout=10,
            )
            return resp.status_code in (200, 201)
    except Exception as e:
        logger.error(f"Email error: {e}")
        return False


async def send_verification_email(email: str, name: str, token: str):
    url = f"https://your-api.railway.app/api/auth/verify-email/{token}"
    await _send(email, "Verify your STRATA account", f"Click to verify: {url}")

async def send_password_reset_email(email: str, name: str, token: str):
    url = f"https://strata.ai/reset-password?token={token}"
    await _send(email, "Reset your STRATA password", f"Click to reset: {url}")

async def send_booking_confirmation_email(email, user_name, expert_name, service_type, scheduled_at, booking_id):
    await _send(email, f"Booking confirmed — {service_type}", f"Session with {expert_name} confirmed. Booking ID: {booking_id}")

async def send_analysis_ready_email(email, user_name, analysis_title, analysis_id):
    await _send(email, f"Your analysis is ready: {analysis_title}", f"Analysis ID: {analysis_id}")

async def send_payment_failed_email(email, user_name, portal_url):
    await _send(email, "Payment failed", f"Update payment: {portal_url}")

async def send_welcome_email(email, user_name):
    await _send(email, "Welcome to STRATA", f"Hey {user_name}, your dashboard is ready.")
