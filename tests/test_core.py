import pytest

from cyberlog import CyberLogConfigurationError, CyberLogCore
from cyberlog.buffer import Buffer


def _make(monkeypatch, fake_transport):
    """Construct a CyberLogCore wired to FakeTransport."""
    from cyberlog import core as core_module

    # Skip the network call done by validate_on_init=True.
    monkeypatch.setattr(
        core_module.Transport,
        "__init__",
        lambda self, **kw: None,
    )
    # Swap the validated-on-init network probe for the fake one.
    def _fake_transport_factory(**kwargs):
        return fake_transport
    monkeypatch.setattr(core_module, "Transport", lambda **kw: fake_transport)
    return CyberLogCore(
        api_key="ccl_test",
        project="my-backend",
        validate_on_init=True,
    )


def test_requires_project():
    with pytest.raises(CyberLogConfigurationError):
        CyberLogCore(api_key="ccl_test", project="")


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("CYBERLOG_API_KEY", raising=False)
    with pytest.raises(CyberLogConfigurationError):
        CyberLogCore(api_key=None, project="x")


def test_log_methods_enqueue_entry(monkeypatch, fake_transport):
    log = _make(monkeypatch, fake_transport)
    try:
        log.info("Hello", user_id="abc")
        log.error("Bad", code=500)
        log.flush(timeout=2.0)

        flat = [e for batch in fake_transport.sent for e in batch]
        assert [e.message for e in flat] == ["Hello", "Bad"]
        assert flat[0].level == "info"
        assert flat[0].fields == {"user_id": "abc"}
        assert flat[1].level == "error"
        assert flat[1].fields == {"code": 500}
    finally:
        log.close(timeout=1.0)


def test_bind_attaches_sticky_fields(monkeypatch, fake_transport):
    log = _make(monkeypatch, fake_transport)
    try:
        child = log.bind(request_id="r-1")
        child.info("First")
        child.info("Second", status=200)
        log.flush(timeout=2.0)

        flat = [e for batch in fake_transport.sent for e in batch]
        assert flat[0].fields == {"request_id": "r-1"}
        # Per-call fields override bound ones if they collide; here they don't.
        assert flat[1].fields == {"request_id": "r-1", "status": 200}
    finally:
        log.close(timeout=1.0)


def test_invalid_level_rejected(monkeypatch, fake_transport):
    log = _make(monkeypatch, fake_transport)
    try:
        with pytest.raises(CyberLogConfigurationError):
            log.log("trace", "nope")
    finally:
        log.close(timeout=1.0)


def test_context_manager_flushes(monkeypatch, fake_transport):
    with _make(monkeypatch, fake_transport) as log:
        log.info("Bye")
    flat = [e for batch in fake_transport.sent for e in batch]
    assert any(e.message == "Bye" for e in flat)


def test_bind_child_does_not_own_io(monkeypatch, fake_transport):
    log = _make(monkeypatch, fake_transport)
    try:
        child = log.bind(x=1)
        assert isinstance(log._buffer, Buffer)          # parent owns it
        assert child._buffer is log._buffer             # child shares
        assert child._owns_io is False                  # but doesn't manage lifecycle
    finally:
        log.close(timeout=1.0)
