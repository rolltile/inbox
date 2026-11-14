"""Configuration for Telnyx SMS Inbox, loaded only from environment variables.

No secret is ever written to a log. Values are read at import time, except
APP_PASSWORD which is compared with hmac.compare_digest and never logged.
"""
import os
from zoneinfo import ZoneInfo


def _int_env(name, default, minimum, maximum):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY", "").strip()
TELNYX_PHONE_NUMBER = os.environ.get("TELNYX_PHONE_NUMBER", "").strip()
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# Automatic refresh, in seconds. The frontend polls every 10 to 15 seconds
# by default. Clamp the value so a bad setting cannot hammer the Telnyx API.
POLL_INTERVAL = _int_env("POLL_INTERVAL", 15, 10, 60)

# How many of the most recent inbound messages to show. Default 3.
MESSAGE_LIMIT = _int_env("MESSAGE_LIMIT", 3, 1, 10)

TIMEZONE_NAME = os.environ.get("TIMEZONE", "UTC").strip() or "UTC"
try:
    TIMEZONE = ZoneInfo(TIMEZONE_NAME)
except Exception:
    TIMEZONE_NAME = "UTC"
    TIMEZONE = ZoneInfo("UTC")

# Minimum seconds between /api/messages calls from one client.
# The frontend polls at POLL_INTERVAL, manual refresh is limited to this.
MIN_REFRESH_SECONDS = 5

# Session lifetime, in seconds.
SESSION_MAX_AGE = 12 * 60 * 60
