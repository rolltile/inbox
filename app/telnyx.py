"""Read-only Telnyx API client.

Only HTTP GET requests are made. No message is sent, deleted, or modified,
and no account setting is changed.

The Telnyx responses observed in practice are not uniform, so every field
is read defensively:
- detail records use ``id`` (not ``uuid``), ``cli`` for the sender,
  ``cld`` for the recipient, ``created_at`` for the timestamp, and
  ``record_type`` may be ``message``. Older examples use ``uuid`` and
  ``message_detail_record``.
- a message uses ``data.text``, ``data.from.phone_number``,
  ``data.to[0].phone_number``, ``data.received_at`` / ``data.sent_at``.
  ``from`` and ``to`` may also arrive as plain strings.
- ``GET /messages/{id}`` only returns a message for up to 10 days. Older
  messages return 404 and are reported as unavailable, not fabricated.
"""
import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from . import config

log = logging.getLogger("telnyx_sms_inbox")
BASE_URL = "https://api.telnyx.com/v2"

# A code mentioned near these words is preferred over any other number.
_OTP_LABEL_RE = re.compile(
    r"(?:verification|verify|otp|passcode|code|pin)[^0-9]{0,25}(\d{4,8})\b",
    re.IGNORECASE,
)
_ANY_CODE_RE = re.compile(r"\b(\d{4,8})\b")


def extract_otp(text: str | None) -> str | None:
    """Return the verification code in a message, or None.

    Prefer a number labelled as a code, then a standalone 6-digit code,
    then any standalone 4 to 8 digit number. Phone numbers and years are
    longer or attached to other digits, so the word boundary matters.
    """
    if not text:
        return None
    labelled = _OTP_LABEL_RE.search(text)
    if labelled:
        return labelled.group(1)
    six = re.search(r"\b(\d{6})\b", text)
    if six:
        return six.group(1)
    any_code = _ANY_CODE_RE.search(text)
    return any_code.group(1) if any_code else None


def parse_timestamp(value):
    """Parse an ISO timestamp to an aware datetime, or None."""
    if not value or not isinstance(value, str):
        return None
    try:
        text = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_timestamp(value, tz: ZoneInfo) -> tuple[str | None, str | None]:
    """Return (iso_utc, local_display) for a timestamp value."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return None, None
    return parsed.isoformat(), parsed.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def _phone(value, key="phone_number"):
    if isinstance(value, dict):
        return value.get(key) or value.get("number") or ""
    if isinstance(value, str):
        return value
    return ""


def _first_phone(value):
    if isinstance(value, list):
        return _phone(value[0]) if value else ""
    return _phone(value)


def parse_detail_record(record: dict) -> dict:
    """Normalise one detail record, tolerating missing or renamed fields."""
    if not isinstance(record, dict):
        return {}
    sender = (
        record.get("cli")
        or _phone(record.get("from"))
        or record.get("sender")
        or ""
    )
    recipient = (
        record.get("cld")
        or _first_phone(record.get("to"))
        or record.get("recipient")
        or ""
    )
    timestamp = (
        record.get("created_at")
        or record.get("sent_at")
        or record.get("received_at")
        or record.get("completed_at")
        or ""
    )
    return {
        "id": record.get("id") or record.get("uuid") or record.get("message_id") or "",
        "direction": record.get("direction") or "",
        "sender": sender,
        "recipient": recipient,
        "timestamp": timestamp,
        "status": record.get("status") or "",
        "message_type": record.get("message_type") or record.get("type") or "",
    }


def parse_message(data: dict, fallback: dict | None = None) -> dict:
    """Normalise one GET /messages/{id} response body."""
    fallback = fallback or {}
    if not isinstance(data, dict):
        data = {}
    sender = _phone(data.get("from")) or fallback.get("sender", "")
    recipient = _first_phone(data.get("to")) or fallback.get("recipient", "")
    timestamp = (
        data.get("received_at")
        or data.get("sent_at")
        or data.get("completed_at")
        or data.get("created_at")
        or fallback.get("timestamp", "")
    )
    text = data.get("text")
    if text is None:
        text = data.get("body") or ""
    return {
        "id": data.get("id") or fallback.get("id", ""),
        "sender": sender,
        "recipient": recipient,
        "timestamp": timestamp,
        "text": text if isinstance(text, str) else "",
        "status": data.get("status") or fallback.get("status", ""),
        "message_type": data.get("type") or fallback.get("message_type", ""),
    }


class TelnyxError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class TelnyxClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _client(self):
        # trust_env=False: do not use ambient HTTP_PROXY / NO_PROXY settings.
        # Those settings vary by host and have broken httpx URL parsing
        # in some sandboxes. The app makes a direct HTTPS call to Telnyx.
        try:
            return httpx.AsyncClient(
                base_url=BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
                timeout=15.0,
                follow_redirects=False,
                trust_env=False,
            )
        except Exception as exc:
            raise TelnyxError(f"Could not create a Telnyx client: {exc.__class__.__name__}") from exc

    async def list_detail_records(self):
        """GET /detail_records, messaging only, newest first."""
        params = {
            "filter[record_type]": "messaging",
            "page[size]": 50,
            "sort": "-created_at",
        }
        async with self._client() as client:
            try:
                response = await client.get("/detail_records", params=params)
            except httpx.RequestError as exc:
                raise TelnyxError(f"Could not reach Telnyx: {exc.__class__.__name__}") from exc
        if response.status_code == 401:
            raise TelnyxError("Telnyx authentication failed (401). Check TELNYX_API_KEY.", status=401)
        if response.status_code == 403:
            raise TelnyxError("Telnyx refused the request (403). Check the API key permissions.", status=403)
        if response.status_code != 200:
            raise TelnyxError(
                f"Telnyx returned HTTP {response.status_code} for detail records.",
                status=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise TelnyxError("Telnyx returned a response that was not JSON.") from exc
        if not isinstance(body, dict):
            raise TelnyxError("Telnyx returned an unexpected detail records response.")
        data = body.get("data")
        if not isinstance(data, list):
            data = []
        meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
        return data, meta.get("total_results")

    async def get_message(self, message_id: str):
        """GET /messages/{id}. Returns None when the message is not found."""
        async with self._client() as client:
            try:
                response = await client.get(f"/messages/{message_id}")
            except httpx.RequestError as exc:
                raise TelnyxError(f"Could not reach Telnyx: {exc.__class__.__name__}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise TelnyxError(
                f"Telnyx returned HTTP {response.status_code} for message {message_id}.",
                status=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise TelnyxError("Telnyx returned a response that was not JSON.") from exc
        if not isinstance(body, dict):
            return None
        data = body.get("data")
        if not isinstance(data, dict):
            return None
        return data

    async def fetch_latest_inbound(self, limit: int):
        """Return the newest inbound messages, with full text where available."""
        if not self.api_key:
            raise TelnyxError("TELNYX_API_KEY is not configured.", status=None)
        records, total_results = await self.list_detail_records()
        parsed = [parse_detail_record(r) for r in records]
        parsed = [r for r in parsed if r.get("direction") == "inbound" and r.get("id")]
        # The API already sorts by -created_at, but sort defensively by timestamp.
        parsed.sort(key=lambda r: parse_timestamp(r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        chosen = parsed[:limit]
        messages = []
        for record in chosen:
            try:
                data = await self.get_message(record["id"])
            except Exception:
                data = None
            if data is None:
                # The record exists but the body is no longer retrievable
                # (for example, older than 10 days). Show the record honestly.
                message = {
                    **record,
                    "text": "",
                    "otp": None,
                    "body_unavailable": True,
                }
            else:
                message = parse_message(data, fallback=record)
                message["otp"] = extract_otp(message.get("text"))
                message["body_unavailable"] = False
            iso, local = format_timestamp(message.get("timestamp"), config.TIMEZONE)
            message["timestamp_iso"] = iso
            message["timestamp_local"] = local or message.get("timestamp", "")
            messages.append(message)
        log.info("Telnyx fetch: %s records, %s inbound, %s shown", len(records), len(parsed), len(messages))
        return {
            "total_results": total_results,
            "inbound_count": len(parsed),
            "messages": messages,
        }
