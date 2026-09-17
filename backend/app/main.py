"""WeatherGPT FastAPI application entrypoint."""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.utils.logging import configure_logging, get_logger, request_id_var

configure_logging(debug=settings.debug)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: init DB, start scheduler, clean shutdown."""
    from app.database.database import init_db, dispose_db
    from app.services.alert_scheduler import start_alert_scheduler, stop_alert_scheduler

    await init_db()
    start_alert_scheduler(app)
    logger.info("WeatherGPT backend started (env=%s)", settings.app_env)
    yield
    stop_alert_scheduler(app)
    await dispose_db()
    logger.info("WeatherGPT backend stopped")


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="AI-powered weather assistant API — "
    "weather data is the source of truth; the AI explains it.",
    lifespan=lifespan,
)

# --------------------------------------------------------------------- #
# Middleware
# --------------------------------------------------------------------- #

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attach a request ID and enforce rate limits per endpoint class."""
    request_id = uuid.uuid4().hex[:12]
    request_id_var.set(request_id)
    request.state.request_id = request_id

    from app.utils.rate_limit import enforce_rate_limit

    if request.method != "OPTIONS":
        try:
            await enforce_rate_limit(request, chat=request.url.path == "/chat")
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": "RATE_LIMITED", "message": exc.detail}},
            )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# --------------------------------------------------------------------- #
# Error handling — clean errors, never raw stack traces
# --------------------------------------------------------------------- #


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Standard error envelope for HTTPException."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": _code_for(exc.status_code), "message": str(exc.detail)}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Standard error envelope for request validation failures."""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request parameters.",
                "details": exc.errors(),
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all handler: log server-side, return a clean 500."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Something went wrong. Please try again shortly.",
            }
        },
    )


def _code_for(status_code: int) -> str:
    """Map HTTP status codes to error codes."""
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        429: "RATE_LIMITED",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "ERROR")


# --------------------------------------------------------------------- #
# Routers
# --------------------------------------------------------------------- #

from app.api.routes_alerts import router as alerts_router  # noqa: E402
from app.api.routes_auth import router as auth_router  # noqa: E402
from app.api.routes_chat import router as chat_router  # noqa: E402
from app.api.routes_insights import router as insights_router  # noqa: E402
from app.api.routes_locations import router as locations_router  # noqa: E402
from app.api.routes_notifications import router as notifications_router  # noqa: E402
from app.api.routes_weather import router as weather_router  # noqa: E402
from app.api.routes_ws import router as ws_router  # noqa: E402

app.include_router(weather_router)
app.include_router(insights_router)
app.include_router(chat_router)
app.include_router(alerts_router)
app.include_router(locations_router)
app.include_router(auth_router)
app.include_router(notifications_router)
app.include_router(ws_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    """API health check."""
    return {"status": "ok"}


@app.get("/llm/status", tags=["health"])
async def llm_status() -> dict:
    """Safe LLM provider health snapshot for debugging/admin.

    Exposes only configured/state/cooldown info — never API keys or
    provider account details (spec §6).
    """
    from app.services.llm_manager import llm_manager

    return llm_manager.get_status()
