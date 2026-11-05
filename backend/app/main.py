import os
import sys
import uuid
import time
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.exceptions import ResponseValidationError
from starlette.responses import Response, StreamingResponse

from app.api.router import router
from app.core.database import Base, engine
from app.utils.exceptions import AppException
from app.models.camera_model import Camera
from app.models.recording_model import Recording
from app.utils.resource_path import resource_path
from app.core.logger import setup_logger, current_request_id
from app.services.realtime_log_service import realtime_log_service

logger = setup_logger("vision-ai")

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Project root = parent of the /app folder
_ROOT = Path(__file__).parent.parent


# ─────────────────────────────────────────
# BOOTSTRAP: .env
# ─────────────────────────────────────────
def _ensure_env_file():
    if getattr(sys, "frozen", False):
        return
    env_path = _ROOT / ".env"
    if not env_path.exists():
        db_path = (_ROOT / "vision_ai.db").resolve().as_posix()
        env_path.write_text(
            f"DATABASE_URL=sqlite:///{db_path}\n"
            "APP_NAME=Vision AI Command Center\n"
            "DEBUG=True\n",
            encoding="utf-8",
        )

_ensure_env_file()


# ─────────────────────────────────────────
# BOOTSTRAP: DB tables + auto column migration
# ─────────────────────────────────────────
def _ensure_tables():
    try:
        from sqlalchemy import inspect, text
        Base.metadata.create_all(bind=engine)

        inspector = inspect(engine)

        if "cameras" in inspector.get_table_names():
            existing_camera_columns = [
                column["name"]
                for column in inspector.get_columns("cameras")
            ]

            camera_migrations = []

            if "recording_video_testing_path" not in existing_camera_columns:
                camera_migrations.append(
                    "ALTER TABLE cameras "
                    "ADD COLUMN recording_video_testing_path VARCHAR"
                )

            if "recording_format" not in existing_camera_columns:
                camera_migrations.append(
                    "ALTER TABLE cameras "
                    "ADD COLUMN recording_format VARCHAR(20) DEFAULT 'MP4'"
                )

            if "clip_duration_minutes" not in existing_camera_columns:
                camera_migrations.append(
                    "ALTER TABLE cameras "
                    "ADD COLUMN clip_duration_minutes INTEGER DEFAULT 1"
                )

            if camera_migrations:
                with engine.begin() as conn:
                    for sql in camera_migrations:
                        conn.execute(text(sql))

        # Contrast schema migration v2 (legacy 0..100 -> -10..+10)
        from app.services.camera_limits_service import run_contrast_migration_v2
        run_contrast_migration_v2(engine)

    except Exception as e:
        logger.warning(f"[BOOTSTRAP] Table migration check: {e}")

_ensure_tables()


# ---------------------------------------------------
#  FastAPI App
# ---------------------------------------------------
app = FastAPI(
    title="Vision Monitor Camera Service",
    version="1.0",
)


def _cors_headers(request: Request) -> dict:
    origin = request.headers.get("origin") or "*"
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }


# ---------------------------------------------------
#  GLOBAL EXCEPTION HANDLERS
# ---------------------------------------------------
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    req_id = getattr(request.state, "request_id", "req_unknown")
    logger.warning(
        f"[APP EXCEPTION] [{req_id}] {request.method} {request.url.path} -> {exc.status_code}: {exc.message}"
    )
    realtime_log_service.add_log(
        "system",
        "WARN",
        f"{request.method} {request.url.path} -> {exc.message}",
        "warning"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": False, "message": exc.message, "detail": exc.message, "data": None, "request_id": req_id},
        headers=_cors_headers(request),
    )


@app.exception_handler(ResponseValidationError)
async def response_validation_exception_handler(request: Request, exc: ResponseValidationError):
    req_id = getattr(request.state, "request_id", "req_unknown")
    logger.error(
        f"[RESPONSE VALIDATION ERROR] [{req_id}] {request.method} {request.url.path}: {exc}",
        exc_info=True
    )
    realtime_log_service.add_log(
        "system",
        "CRASH",
        f"Validation error on {request.method} {request.url.path}",
        "error"
    )
    return JSONResponse(
        status_code=500,
        content={
            "status": False,
            "message": "Response validation error (endpoint returned invalid data)",
            "request_id": req_id,
            "detail": str(exc)
        },
        headers=_cors_headers(request),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", "req_unknown")
    logger.error(
        f"[CRASH 500] [{req_id}] Unhandled exception in {request.method} {request.url.path}: {exc}",
        exc_info=True
    )
    realtime_log_service.add_log(
        "system",
        "CRASH",
        f"500 on {request.method} {request.url.path}: {exc}",
        "error"
    )
    return JSONResponse(
        status_code=500,
        content={"status": False, "message": f"Internal Server Error: {exc}", "detail": str(exc), "request_id": req_id, "data": None},
        headers=_cors_headers(request),
    )


# Paths whose responses must NOT be buffered/read (streaming / binary)
STREAMING_PATH_PREFIXES = (
    "/oak/stream",
    "/oak/snapshot",
)

# ---------------------------------------------------
#  API REQUEST & CRASH LOGGING MIDDLEWARE
# ---------------------------------------------------
@app.middleware("http")
async def api_logging_middleware(request: Request, call_next):
    start_time = time.time()
    req_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:8]}"
    request.state.request_id = req_id
    token = current_request_id.set(req_id)
    method = request.method
    path = request.url.path

    try:
        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = round((time.time() - start_time) * 1000, 1)
            logger.error(
                f"[API CRASH] {method} {path} failed after {duration_ms}ms: {e}",
                exc_info=True,
            )
            realtime_log_service.add_log(
                "system",
                "CRASH",
                f"Unhandled error in {method} {path}: {e}",
                "error"
            )
            headers = _cors_headers(request)
            headers["X-Request-ID"] = req_id
            return JSONResponse(
                status_code=500,
                content={"status": False, "message": str(e), "detail": str(e), "request_id": req_id},
                headers=headers,
            )

        duration_ms = round((time.time() - start_time) * 1000, 1)

        is_streaming = (
            isinstance(response, StreamingResponse)
            or any(path.startswith(p) for p in STREAMING_PATH_PREFIXES)
        )

        if is_streaming:
            if response.status_code >= 400:
                logger.warning(f"[API WARN] {method} {path} -> {response.status_code} ({duration_ms}ms)")
            else:
                logger.info(f"[API] {method} {path} -> {response.status_code} ({duration_ms}ms)")
            response.headers["X-Request-ID"] = req_id
            return response

        if response.status_code >= 400:
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    detail = parsed.get("detail") or parsed.get("message") or parsed
                else:
                    detail = parsed
            except Exception:
                detail = body.decode(errors="ignore")[:300]

            if response.status_code >= 500:
                if path == "/health" and response.status_code == 503:
                    logger.debug(
                        f"[API] {method} {path} -> 503 ({duration_ms}ms) | {detail}"
                    )
                elif response.status_code == 503 and path.startswith("/oak/stream"):
                    logger.warning(
                        f"[API WARN] {method} {path} -> 503 ({duration_ms}ms) | {detail}"
                    )
                else:
                    logger.error(
                        f"[API ERROR] {method} {path} -> {response.status_code} ({duration_ms}ms) | {detail}"
                    )
            else:
                logger.warning(
                    f"[API WARN] {method} {path} -> {response.status_code} ({duration_ms}ms) | {detail}"
                )

            headers = dict(response.headers)
            headers["content-length"] = str(len(body))
            headers["X-Request-ID"] = req_id
            if "access-control-allow-origin" not in {k.lower() for k in headers.keys()}:
                headers.update(_cors_headers(request))
            response = Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=response.media_type,
            )
            return response
        else:
            is_routine_poll = path in ("/health", "/oak/health")
            if not is_routine_poll:
                logger.info(f"[API] {method} {path} -> {response.status_code} ({duration_ms}ms)")

            response.headers["X-Request-ID"] = req_id
            return response
    finally:
        current_request_id.reset(token)


# ---------------------------------------------------
#  CORS
# ---------------------------------------------------
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1",
    "http://localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "app://localhost"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://.*$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------
#  STATIC FILES (if storage directory exists)
# ---------------------------------------------------
storage_dir = resource_path("storage")
if os.path.exists(storage_dir):
    app.mount(
        "/storage",
        StaticFiles(directory=storage_dir),
        name="storage"
    )

# ---------------------------------------------------
#  HEALTH CHECK & SYSTEM CONTROL
# ---------------------------------------------------
@app.get("/health", tags=["System"])
async def get_health():
    """Health check endpoint for frontend readiness polling."""
    return {"status": "ready", "message": "Backend is healthy", "data": None}


@app.post("/api/system/shutdown", tags=["System"])
def shutdown_system():
    """Endpoint for graceful desktop exit requested by Electron."""
    import threading
    import signal

    def _delayed_exit():
        time.sleep(0.5)
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            os._exit(0)

    threading.Thread(target=_delayed_exit, daemon=True).start()
    return {"status": "shutting_down", "message": "Backend terminating cleanly"}


# ---------------------------------------------------
#  REGISTER ROUTES
# ---------------------------------------------------
app.include_router(router)
