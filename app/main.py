"""Telnyx SMS Inbox 1.0 - FastAPI backend.

Read-only SMS inbox. Only GET requests are made to Telnyx. There is no
endpoint that sends, deletes, or modifies anything, and no endpoint that
returns SMS messages without a valid session cookie.

Never log the API key or a complete SMS message body.
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config
from .telnyx import TelnyxClient, TelnyxError

log = logging.getLogger("telnyx_sms_inbox")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Telnyx SMS Inbox", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# In-memory rate limiting only. No database, no Redis.
_last_fetch_by_client: dict[str, float] = {}
_login_attempts: dict[str, list[float]] = {}
_cached_result: dict = {}
_cached_at: float = 0.0
_CACHE_SECONDS = 5.0


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; base-uri 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def _is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def _login_response(request: Request):
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_session_token(),
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )
    return response


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index(request: Request):
    if not auth.is_valid_session(request.cookies.get(auth.COOKIE_NAME)):
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse(BASE_DIR / "templates" / "index.html")


@app.get("/login")
async def login_page(request: Request):
    if auth.is_valid_session(request.cookies.get(auth.COOKIE_NAME)):
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(BASE_DIR / "templates" / "login.html")


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    key = _client_key(request)
    now = time.time()
    attempts = [t for t in _login_attempts.get(key, []) if now - t < 60]
    if len(attempts) >= 5:
        return JSONResponse({"error": "Too many login attempts. Try again in a minute."}, status_code=429)
    attempts.append(now)
    _login_attempts[key] = attempts
    if not auth.check_password(password):
        return FileResponse(BASE_DIR / "templates" / "login.html", status_code=401)
    return _login_response(request)


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


@app.get("/api/status")
async def api_status(request: Request):
    if not auth.is_valid_session(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if not config.TELNYX_API_KEY:
        return {
            "connected": False,
            "phone_number": config.TELNYX_PHONE_NUMBER,
            "timezone": config.TIMEZONE_NAME,
            "poll_interval": config.POLL_INTERVAL,
            "message_limit": config.MESSAGE_LIMIT,
            "error": "TELNYX_API_KEY is not configured.",
        }
    return {
        "connected": True,
        "phone_number": config.TELNYX_PHONE_NUMBER,
        "timezone": config.TIMEZONE_NAME,
        "poll_interval": config.POLL_INTERVAL,
        "message_limit": config.MESSAGE_LIMIT,
        "error": None,
    }


@app.get("/api/messages")
async def api_messages(request: Request):
    if not auth.is_valid_session(request.cookies.get(auth.COOKIE_NAME)):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    key = _client_key(request)
    now = time.time()
    last = _last_fetch_by_client.get(key, 0)
    if now - last < config.MIN_REFRESH_SECONDS:
        retry = int(config.MIN_REFRESH_SECONDS - (now - last)) + 1
        return JSONResponse(
            {"error": "rate_limited", "retry_after_seconds": retry},
            status_code=429,
        )
    _last_fetch_by_client[key] = now

    global _cached_result, _cached_at
    if _cached_result and now - _cached_at < _CACHE_SECONDS:
        return _cached_result

    if not config.TELNYX_API_KEY:
        return JSONResponse(
            {"error": "TELNYX_API_KEY is not configured.", "connected": False},
            status_code=503,
        )
    try:
        result = await TelnyxClient(config.TELNYX_API_KEY).fetch_latest_inbound(config.MESSAGE_LIMIT)
    except TelnyxError as exc:
        log.warning("Telnyx fetch failed: %s", exc)
        return JSONResponse(
            {"error": str(exc), "connected": False, "messages": [], "total_results": None},
            status_code=exc.status or 502,
        )
    except Exception as exc:  # Never return a bare 500 for a Telnyx failure.
        log.warning("Telnyx fetch failed: %s", exc.__class__.__name__)
        return JSONResponse(
            {"error": "Could not retrieve messages from Telnyx.", "connected": False, "messages": [], "total_results": None},
            status_code=502,
        )
    payload = {
        "connected": True,
        "phone_number": config.TELNYX_PHONE_NUMBER,
        "timezone": config.TIMEZONE_NAME,
        "poll_interval": config.POLL_INTERVAL,
        "message_limit": config.MESSAGE_LIMIT,
        "last_updated": datetime.now(timezone.utc).astimezone(config.TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "total_results": result.get("total_results"),
        "inbound_count": result.get("inbound_count"),
        "messages": result.get("messages", []),
        "error": None,
    }
    _cached_result = payload
    _cached_at = now
    return payload


@app.on_event("startup")
async def startup():
    if not config.APP_PASSWORD:
        raise RuntimeError("APP_PASSWORD is not set. Set it in the environment before starting the app.")
    if not config.TELNYX_API_KEY:
        log.warning("TELNYX_API_KEY is not set. The inbox will show a configuration error until it is set.")
