"""
STRATA Backend — Test Suite
Run: pytest tests/ -v
Run with coverage: pytest tests/ -v --cov=. --cov-report=term-missing
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from main import app
from database import get_db, Base

# ── Test database (SQLite in-memory) ─────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine, class_=AsyncSession,
    expire_on_commit=False, autoflush=False,
)


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def registered_user(client: AsyncClient):
    """Registers a user and returns (user_data, tokens)."""
    resp = await client.post("/api/auth/register", json={
        "email": "test@strata.ai",
        "password": "Testpass1",
        "full_name": "Test User",
        "company_name": "Test Co",
    })
    assert resp.status_code == 201, resp.text
    tokens = resp.json()
    return {"email": "test@strata.ai", "password": "Testpass1"}, tokens


@pytest_asyncio.fixture
async def auth_headers(registered_user):
    _, tokens = registered_user
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ── Health ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("healthy", "degraded")
    assert "checks" in data


@pytest.mark.asyncio
async def test_root(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json()["service"] == "STRATA API"


# ── Auth ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={
        "email": "new@strata.ai",
        "password": "Secure123",
        "full_name": "New User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    payload = {"email": "dup@strata.ai", "password": "Secure123", "full_name": "User"}
    await client.post("/api/auth/register", json=payload)
    resp = await client.post("/api/auth/register", json=payload)
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_weak_password(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={
        "email": "weak@strata.ai",
        "password": "password",
        "full_name": "Weak Pass",
    })
    assert resp.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, registered_user):
    user_data, _ = registered_user
    resp = await client.post("/api/auth/login", json=user_data)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient, registered_user):
    user_data, _ = registered_user
    resp = await client.post("/api/auth/login", json={
        "email": user_data["email"],
        "password": "WrongPass1",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client: AsyncClient, auth_headers):
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@strata.ai"
    assert data["plan"] == "free"


@pytest.mark.asyncio
async def test_refresh_token(client: AsyncClient, registered_user):
    _, tokens = registered_user
    resp = await client.post("/api/auth/refresh", json={
        "refresh_token": tokens["refresh_token"]
    })
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert "access_token" in new_tokens
    # Old refresh token should be revoked — cannot use again
    resp2 = await client.post("/api/auth/refresh", json={
        "refresh_token": tokens["refresh_token"]
    })
    assert resp2.status_code == 401


@pytest.mark.asyncio
async def test_logout(client: AsyncClient, registered_user, auth_headers):
    _, tokens = registered_user
    resp = await client.post("/api/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_no_auth_returns_401(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 403  # HTTPBearer returns 403 when no token


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client: AsyncClient):
    resp = await client.get("/api/auth/me",
        headers={"Authorization": "Bearer not.a.valid.token"})
    assert resp.status_code == 401


# ── Analyses ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_analysis(client: AsyncClient, auth_headers):
    # First verify email
    async with TestSessionLocal() as db:
        from sqlalchemy import select
        from models import User
        result = await db.execute(select(User).where(User.email == "test@strata.ai"))
        user = result.scalar_one()
        user.is_verified = True
        await db.commit()

    resp = await client.post("/api/analyses/", json={
        "stage": "startup",
        "analysis_type": "customer_intel",
        "title": "Test Customer Analysis",
        "input_data": {"product": "Test SaaS", "industry": "B2B"},
        "tags": ["test", "saas"],
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test Customer Analysis"
    assert data["stage"] == "startup"
    assert data["analysis_type"] == "customer_intel"
    assert data["is_starred"] is False
    return data["id"]


@pytest.mark.asyncio
async def test_list_analyses(client: AsyncClient, auth_headers):
    # Need verified user
    async with TestSessionLocal() as db:
        from sqlalchemy import select
        from models import User
        result = await db.execute(select(User).where(User.email == "test@strata.ai"))
        user = result.scalar_one()
        user.is_verified = True
        await db.commit()

    # Create 3 analyses
    for i in range(3):
        await client.post("/api/analyses/", json={
            "stage": "startup",
            "analysis_type": "customer_intel",
            "title": f"Analysis {i}",
            "input_data": {},
        }, headers=auth_headers)

    resp = await client.get("/api/analyses/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


@pytest.mark.asyncio
async def test_star_analysis(client: AsyncClient, auth_headers):
    async with TestSessionLocal() as db:
        from sqlalchemy import select
        from models import User
        result = await db.execute(select(User).where(User.email == "test@strata.ai"))
        user = result.scalar_one()
        user.is_verified = True
        await db.commit()

    create_resp = await client.post("/api/analyses/", json={
        "stage": "growth", "analysis_type": "gtm_playbook",
        "title": "Star Test", "input_data": {},
    }, headers=auth_headers)
    analysis_id = create_resp.json()["id"]

    star_resp = await client.post(f"/api/analyses/{analysis_id}/star", headers=auth_headers)
    assert star_resp.status_code == 200
    assert star_resp.json()["is_starred"] is True

    # Toggle back
    unstar_resp = await client.post(f"/api/analyses/{analysis_id}/star", headers=auth_headers)
    assert unstar_resp.json()["is_starred"] is False


@pytest.mark.asyncio
async def test_delete_analysis(client: AsyncClient, auth_headers):
    async with TestSessionLocal() as db:
        from sqlalchemy import select
        from models import User
        result = await db.execute(select(User).where(User.email == "test@strata.ai"))
        user = result.scalar_one()
        user.is_verified = True
        await db.commit()

    create_resp = await client.post("/api/analyses/", json={
        "stage": "enterprise", "analysis_type": "board_brief",
        "title": "Delete Me", "input_data": {},
    }, headers=auth_headers)
    analysis_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/analyses/{analysis_id}", headers=auth_headers)
    assert del_resp.status_code == 200

    get_resp = await client.get(f"/api/analyses/{analysis_id}", headers=auth_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_analysis_isolation(client: AsyncClient):
    """User A cannot access User B's analyses."""
    # Register user A
    await client.post("/api/auth/register", json={
        "email": "usera@strata.ai", "password": "UserA123", "full_name": "User A",
    })
    login_a = await client.post("/api/auth/login", json={
        "email": "usera@strata.ai", "password": "UserA123",
    })
    headers_a = {"Authorization": f"Bearer {login_a.json()['access_token']}"}

    # Register user B
    await client.post("/api/auth/register", json={
        "email": "userb@strata.ai", "password": "UserB123", "full_name": "User B",
    })
    login_b = await client.post("/api/auth/login", json={
        "email": "userb@strata.ai", "password": "UserB123",
    })
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    # Verify both
    async with TestSessionLocal() as db:
        from sqlalchemy import select
        from models import User
        for email in ("usera@strata.ai", "userb@strata.ai"):
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one()
            user.is_verified = True
        await db.commit()

    # User A creates an analysis
    create_resp = await client.post("/api/analyses/", json={
        "stage": "startup", "analysis_type": "customer_intel",
        "title": "A's Private Analysis", "input_data": {},
    }, headers=headers_a)
    analysis_id = create_resp.json()["id"]

    # User B tries to access it
    resp = await client.get(f"/api/analyses/{analysis_id}", headers=headers_b)
    assert resp.status_code == 404


# ── Billing ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_subscription_free_user(client: AsyncClient, auth_headers):
    resp = await client.get("/api/billing/subscription", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "free"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_get_limits_free_user(client: AsyncClient, auth_headers):
    async with TestSessionLocal() as db:
        from sqlalchemy import select
        from models import User
        result = await db.execute(select(User).where(User.email == "test@strata.ai"))
        user = result.scalar_one()
        user.is_verified = True
        await db.commit()

    resp = await client.get("/api/billing/limits", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["plan"] == "free"
    assert data["tokens_remaining"] > 0
    assert data["can_use_human_services"] is False


# ── Experts + Bookings ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_experts_empty(client: AsyncClient):
    """Experts list is public and returns empty when no experts seeded."""
    resp = await client.get("/api/booking/experts")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── AI Usage ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_usage_endpoint(client: AsyncClient, auth_headers):
    async with TestSessionLocal() as db:
        from sqlalchemy import select
        from models import User
        result = await db.execute(select(User).where(User.email == "test@strata.ai"))
        user = result.scalar_one()
        user.is_verified = True
        await db.commit()

    resp = await client.get("/api/ai/usage", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "tokens_used_month" in data
    assert "tokens_remaining" in data
    assert data["plan"] == "free"


# ── Pagination ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyses_pagination(client: AsyncClient, auth_headers):
    async with TestSessionLocal() as db:
        from sqlalchemy import select
        from models import User
        result = await db.execute(select(User).where(User.email == "test@strata.ai"))
        user = result.scalar_one()
        user.is_verified = True
        await db.commit()

    for i in range(15):
        await client.post("/api/analyses/", json={
            "stage": "startup", "analysis_type": "customer_intel",
            "title": f"Paginated {i}", "input_data": {},
        }, headers=auth_headers)

    page1 = await client.get("/api/analyses/?page=1&per_page=10", headers=auth_headers)
    assert page1.status_code == 200
    assert len(page1.json()["items"]) == 10
    assert page1.json()["total"] == 15
    assert page1.json()["pages"] == 2

    page2 = await client.get("/api/analyses/?page=2&per_page=10", headers=auth_headers)
    assert len(page2.json()["items"]) == 5
