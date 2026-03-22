from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import time

from config import settings
from database import engine, Base
from routes import auth, analyses, ai, billing, booking, admin, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("strata")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("STRATA API starting up...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")
    yield
    logger.info("STRATA API shutting down")


app = FastAPI(
    title="STRATA API",
    description="Strategy Intelligence Platform — Backend API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Response-Time"] = f"{duration_ms}ms"
    logger.info(f"{request.method} {request.url.path}  {response.status_code}  {duration_ms}ms")
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again."},
    )


app.include_router(health.router,   prefix="/health",       tags=["Health"])
app.include_router(auth.router,     prefix="/api/auth",     tags=["Auth"])
app.include_router(analyses.router, prefix="/api/analyses", tags=["Analyses"])
app.include_router(ai.router,       prefix="/api/ai",       tags=["AI"])
app.include_router(billing.router,  prefix="/api/billing",  tags=["Billing"])
app.include_router(booking.router,  prefix="/api/booking",  tags=["Booking"])
app.include_router(admin.router,    prefix="/api/admin",    tags=["Admin"])


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "STRATA API", "version": "1.0.0", "status": "operational"}
