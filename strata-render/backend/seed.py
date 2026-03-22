"""
Seed script — run once after first deploy to create the admin user and
seed expert profiles for the Human Services section.

Usage:  python seed.py
        DATABASE_URL=... python seed.py
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

from database import Base
from models import User, Expert
from auth_utils import hash_password
from config import settings


engine = create_async_engine(settings.DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

EXPERTS = [
    {
        "name": "Marcus Chen",
        "title": "Senior Strategy Partner · STRATA Advisory",
        "bio": "Former strategy lead at two $100M+ SaaS companies. Specialises in growth-stage GTM, chasm crossing, and Series B positioning. 12 years across APAC and North America.",
        "specialties": ["GTM Strategy", "Chasm Crossing", "Series A–C", "Unit Economics"],
        "stages": ["startup", "growth"],
        "rating": 4.9,
        "sessions_count": 142,
        "price_per_hour": 29900,
        "is_available": True,
    },
    {
        "name": "Priya Sharma",
        "title": "Enterprise Strategy Director · STRATA Advisory",
        "bio": "SVP Strategy at a Fortune 500 FMCG company for 8 years before joining STRATA. Expert in portfolio intelligence, BCG/VRIO analysis, and board-level strategic briefs across 15+ markets.",
        "specialties": ["Portfolio Strategy", "VRIO Analysis", "Multi-Market", "Board Briefs"],
        "stages": ["enterprise"],
        "rating": 4.8,
        "sessions_count": 89,
        "price_per_hour": 39900,
        "is_available": True,
    },
    {
        "name": "David Okonkwo",
        "title": "PMF & Customer Discovery Lead · STRATA Advisory",
        "bio": "0-to-1 specialist with 6 startup exits. Deep expertise in customer discovery, PMF validation, JTBD methodology, and pre-seed positioning. Has run 400+ customer discovery interviews.",
        "specialties": ["PMF Validation", "Customer Discovery", "JTBD", "Pre-Seed"],
        "stages": ["startup"],
        "rating": 5.0,
        "sessions_count": 203,
        "price_per_hour": 29900,
        "is_available": True,
    },
    {
        "name": "Sarah Mitchell",
        "title": "GTM Scale Strategist · STRATA Advisory",
        "bio": "Head of Revenue Strategy at two PLG companies before STRATA. Specialises in CAC/LTV optimisation, segment sequencing, and crossing the chasm from $2M to $20M ARR.",
        "specialties": ["PLG", "NRR", "Segment Sequencing", "CAC Optimisation"],
        "stages": ["growth"],
        "rating": 4.9,
        "sessions_count": 117,
        "price_per_hour": 29900,
        "is_available": True,
    },
]


async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("✓ Tables created / verified")

    async with SessionLocal() as db:
        # ── Admin user ────────────────────────────────────────────────────────
        admin_email = settings.ADMIN_EMAIL
        if admin_email:
            result = await db.execute(select(User).where(User.email == admin_email))
            existing_admin = result.scalar_one_or_none()
            if not existing_admin:
                admin = User(
                    email=admin_email,
                    hashed_password=hash_password("ChangeMe123!"),
                    full_name="STRATA Admin",
                    is_admin=True,
                    is_verified=True,
                    is_active=True,
                )
                db.add(admin)
                print(f"✓ Admin created: {admin_email}  (password: ChangeMe123! — change immediately!)")
            else:
                if not existing_admin.is_admin:
                    existing_admin.is_admin = True
                    print(f"✓ Existing user {admin_email} promoted to admin")
                else:
                    print(f"  Admin already exists: {admin_email}")

        # ── Experts ───────────────────────────────────────────────────────────
        existing_experts = (await db.execute(select(Expert))).scalars().all()
        if not existing_experts:
            for e in EXPERTS:
                expert = Expert(**e)
                db.add(expert)
            print(f"✓ Seeded {len(EXPERTS)} experts")
        else:
            print(f"  Experts already seeded ({len(existing_experts)} found)")

        await db.commit()

    print("\n✅ Seed complete. You're ready to go.")
    if settings.ADMIN_EMAIL:
        print(f"   Login: {settings.ADMIN_EMAIL} / ChangeMe123!")
        print("   ⚠️  Change the admin password immediately via /api/auth/change-password")


if __name__ == "__main__":
    asyncio.run(seed())
