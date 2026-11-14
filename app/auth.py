"""Password authentication with a signed, HttpOnly session cookie.

Only the APP_PASSWORD is accepted. The cookie is an HMAC-signed expiry
timestamp, so no session is stored on disk or in a database. The signing
key is random per process start, so sessions end when the app restarts.
"""
import base64
import hashlib
import hmac
import os
import time

from . import config

COOKIE_NAME = "sms_inbox_session"
_SECRET = os.urandom(32)


def _signature(expiry: int) -> str:
    message = f"telnyx-sms-inbox:{expiry}".encode()
    return hmac.new(_SECRET, message, hashlib.sha256).hexdigest()


def create_session_token() -> str:
    expiry = int(time.time()) + config.SESSION_MAX_AGE
    raw = f"{expiry}.{_signature(expiry)}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def is_valid_session(token: str | None) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        expiry_text, signature = raw.split(".", 1)
        expiry = int(expiry_text)
    except Exception:
        return False
    if expiry < int(time.time()):
        return False
    return hmac.compare_digest(signature, _signature(expiry))


def check_password(candidate: str) -> bool:
    password = config.APP_PASSWORD
    if not password:
        return False
    return hmac.compare_digest(candidate, password)
