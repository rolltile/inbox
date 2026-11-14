"""Tests for Telnyx response parsing, using the actual response shapes
observed from the live Telnyx API. No network is used. No real credentials
or real message bodies are included here; values are placeholders.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.telnyx import extract_otp, format_timestamp, parse_detail_record, parse_message
from zoneinfo import ZoneInfo


def test_detail_record_actual_shape():
    # Shape returned by GET /detail_records?filter[record_type]=messaging
    record = {
        "id": "4e3d64a2-0000-4000-8000-000000000000",
        "record_type": "message",
        "direction": "inbound",
        "cli": "22395",
        "cld": "+15551234567",
        "created_at": "2026-11-14T02:57:33Z",
        "status": "received",
        "message_type": "SMS",
    }
    parsed = parse_detail_record(record)
    assert parsed["id"] == record["id"]
    assert parsed["sender"] == "22395"
    assert parsed["recipient"] == "+15551234567"
    assert parsed["timestamp"] == "2026-11-14T02:57:33Z"


def test_detail_record_older_shape():
    # Older documented shape, with uuid instead of id.
    record = {
        "uuid": "3ca7bd3d-0000-4000-8000-000000000000",
        "record_type": "message_detail_record",
        "direction": "outbound",
        "cli": "+15551234567",
        "cld": "+15557654321",
        "created_at": "2020-07-01T00:00:00Z",
        "status": "delivered",
    }
    parsed = parse_detail_record(record)
    assert parsed["id"] == record["uuid"]
    assert parsed["direction"] == "outbound"


def test_message_actual_shape():
    # Shape returned by GET /messages/{id}
    data = {
        "id": "4e3d64a2-0000-4000-8000-000000000000",
        "record_type": "message",
        "direction": "inbound",
        "type": "SMS",
        "from": {"phone_number": "22395", "carrier": "", "line_type": ""},
        "to": [{"phone_number": "+15551234567", "status": "delivery_unconfirmed"}],
        "received_at": "2026-11-14T02:57:33.090+00:00",
        "sent_at": "2026-11-14T02:57:33.090+00:00",
        "text": "Your verification code is: 123456",
        "media": [],
        "encoding": "GSM-7",
    }
    parsed = parse_message(data)
    assert parsed["sender"] == "22395"
    assert parsed["recipient"] == "+15551234567"
    assert parsed["text"] == "Your verification code is: 123456"
    assert extract_otp(parsed["text"]) == "123456"


def test_message_missing_fields():
    parsed = parse_message({}, fallback={"id": "x", "sender": "+15550000000", "recipient": "+15551234567", "timestamp": "2026-11-14T00:00:00Z"})
    assert parsed["sender"] == "+15550000000"
    assert parsed["text"] == ""
    assert extract_otp(parsed["text"]) is None


def test_otp_variants():
    assert extract_otp("Your code is 987654") == "987654"
    assert extract_otp("Code: 1234. Do not share it.") == "1234"
    assert extract_otp("Hello, no code here") is None


def test_timestamp_timezone():
    iso, local = format_timestamp("2026-11-14T02:57:33Z", ZoneInfo("Europe/Rome"))
    assert iso.startswith("2026-11-14T02:57:33")
    assert local.startswith("2026-11-14 03:57:33")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All parsing tests passed.")
