from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
import time

router = APIRouter()

@router.get("/")
async def health(db: AsyncSession = Depends(get_db)):
    checks = {"api": "ok", "database": "unknown", "redis": "not configured"}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:60]}"

    try:
        from middleware.rate_limit import get_redis
        r = get_redis()
        if r:
            await r.ping()
            checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)[:60]}"

    all_critical_ok = checks["database"] == "ok"
    status = "healthy" if all_critical_ok else "degraded"
    return {"status": status, "checks": checks, "timestamp": time.time()}
