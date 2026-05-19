from datetime import datetime, timezone

from cyberlog.models import CyberLogEntry


def test_entry_to_dict_round_trip():
    entry = CyberLogEntry(
        level="error",
        message="Payment failed",
        project="my-backend",
        fields={"order_id": "xyz", "amount": 99.99},
    )
    out = entry.to_dict()
    assert out["level"]   == "error"
    assert out["message"] == "Payment failed"
    assert out["project"] == "my-backend"
    assert out["fields"]  == {"order_id": "xyz", "amount": 99.99}
    # Timestamp is ISO-8601 and parseable.
    assert datetime.fromisoformat(out["timestamp"])


def test_entry_default_timestamp_is_utc():
    entry = CyberLogEntry(level="info", message="x", project="p")
    parsed = datetime.fromisoformat(entry.timestamp)
    assert parsed.tzinfo is not None
    # Generated at most a couple of seconds ago.
    delta = abs((datetime.now(timezone.utc) - parsed).total_seconds())
    assert delta < 5


def test_entry_repr_includes_fields():
    e = CyberLogEntry(level="info", message="hello", project="p", fields={"k": "v"})
    r = repr(e)
    assert "INFO"  in r
    assert "hello" in r
    assert "k="    in r
