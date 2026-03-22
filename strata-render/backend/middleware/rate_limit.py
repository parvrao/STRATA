"""
Rate limiter — Redis-backed when available, no-op fallback when Redis is absent.
On Render free tier Redis may not be available — the API still works, just without rate limiting.
"""

from fastapi import HTTPException, Request
from functools import partial
from config import settings
import time
import logging

logger = logging.getLogger("strata.ratelimit")
_pool = None
_redis_available = None


def get_redis():
    global _pool, _redis_available
    if _redis_available is False:
        return None
    if _pool is None:
        try:
            import redis.asyncio as redis
            _pool = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            _redis_available = True
        except Exception as e:
            logger.warning(f"Redis unavailable — rate limiting disabled: {e}")
            _redis_available = False
            return None
    return _pool


def rate_limit(max_requests: int, window_seconds: int = 60, key_prefix: str = "rl"):
    async def _limiter(request: Request):
        r = get_redis()
        if r is None:
            return  # Redis not available — skip rate limiting gracefully

        client_key = getattr(request.state, "user_id", None) or (request.client.host if request.client else "anon")
        redis_key = f"{key_prefix}:{client_key}:{request.url.path}"
        now = int(time.time())
        window_start = now - window_seconds

        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zadd(redis_key, {str(now) + str(time.time_ns()): now})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds + 1)
            results = await pipe.execute()
            count = results[2]
            if count > max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {max_requests} requests per {window_seconds}s.",
                    headers={"Retry-After": str(window_seconds)},
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Rate limit check failed: {e}")
            # Don't crash the request if Redis has an issue

    return _limiter


auth_limit   = rate_limit(settings.RATE_LIMIT_AUTH,   60, "rl:auth")
ai_limit     = rate_limit(settings.RATE_LIMIT_AI,     60, "rl:ai")
global_limit = rate_limit(settings.RATE_LIMIT_GLOBAL, 60, "rl:global")
strict_limit = rate_limit(5, 60, "rl:strict")
