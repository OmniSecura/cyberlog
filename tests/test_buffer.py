import time

from cyberlog.buffer import Buffer
from cyberlog.models import CyberLogEntry
from cyberlog.transport import SendResult, SendStatus


def _entry(message: str = "hi") -> CyberLogEntry:
    return CyberLogEntry(level="info", message=message, project="t")


def test_single_entry_is_sent(fake_transport):
    buf = Buffer(fake_transport, flush_interval=0.05, batch_size=10)
    try:
        buf.add(_entry())
        assert buf.flush(timeout=2.0)
        assert len(fake_transport.sent) == 1
        assert fake_transport.sent[0][0].message == "hi"
    finally:
        buf.close(timeout=1.0)


def test_batches_are_capped_at_batch_size(fake_transport):
    buf = Buffer(fake_transport, flush_interval=0.05, batch_size=3)
    try:
        for i in range(7):
            buf.add(_entry(f"e{i}"))
        assert buf.flush(timeout=3.0)

        # Total entries delivered = 7, distributed across batches of size <= 3.
        delivered = sum(len(b) for b in fake_transport.sent)
        assert delivered == 7
        assert all(len(b) <= 3 for b in fake_transport.sent)
    finally:
        buf.close(timeout=1.0)


def test_split_on_413(fake_transport):
    fake_transport.scripted = [
        SendResult(SendStatus.SPLIT, detail="too big"),
        SendResult(SendStatus.OK,    accepted=2),
        SendResult(SendStatus.OK,    accepted=2),
    ]
    buf = Buffer(fake_transport, flush_interval=0.05, batch_size=10)
    try:
        for i in range(4):
            buf.add(_entry(f"e{i}"))
        assert buf.flush(timeout=3.0)
        # First attempt + two halves.
        assert len(fake_transport.sent) == 3
        assert len(fake_transport.sent[0]) == 4
        assert len(fake_transport.sent[1]) == 2
        assert len(fake_transport.sent[2]) == 2
    finally:
        buf.close(timeout=1.0)


def test_retry_then_success(fake_transport):
    fake_transport.scripted = [
        SendResult(SendStatus.RETRY, detail="503"),
        SendResult(SendStatus.OK,    accepted=1),
    ]
    buf = Buffer(
        fake_transport,
        flush_interval=0.05,
        batch_size=10,
        backoff_initial=0.01,   # keep the test snappy
        backoff_max=0.05,
        max_retries=3,
    )
    try:
        buf.add(_entry())
        assert buf.flush(timeout=3.0)
        # First attempt failed, second succeeded.
        assert len(fake_transport.sent) == 2
    finally:
        buf.close(timeout=1.0)


def test_auth_failure_silences_buffer(fake_transport):
    fake_transport.scripted = [SendResult(SendStatus.AUTH_FAIL, detail="401")]
    buf = Buffer(fake_transport, flush_interval=0.05, batch_size=10)
    try:
        buf.add(_entry("first"))
        # Wait for the auth failure to register.
        time.sleep(0.5)
        # Subsequent adds become no-ops.
        buf.add(_entry("second"))
        buf.add(_entry("third"))
        time.sleep(0.3)

        # Only the first entry was ever handed to the transport.
        all_sent = [e for batch in fake_transport.sent for e in batch]
        assert [e.message for e in all_sent] == ["first"]
    finally:
        buf.close(timeout=1.0)
