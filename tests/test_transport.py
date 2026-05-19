"""
Network-level tests for `Transport`. We mount an httpx MockTransport so no
real socket is opened.
"""
from __future__ import annotations

import json

import httpx
import pytest

from cyberlog.exceptions import CyberLogAuthError, CyberLogTransportError
from cyberlog.models import CyberLogEntry
from cyberlog.transport import SendStatus, Transport


def _make_transport(handler, *, api_url: str = "https://example.test/api/v1") -> Transport:
    t = Transport(api_url=api_url, api_key="ccl_x")
    t._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer ccl_x"},
    )
    return t


def test_validate_success():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/auth/validate")
        return httpx.Response(200, json={"org_id": "o1", "key_id": "k1", "key_name": "ci"})

    t = _make_transport(handler)
    info = t.validate()
    assert info["org_id"] == "o1"


def test_validate_auth_failure():
    def handler(req): return httpx.Response(401, json={"detail": "Invalid or revoked API key."})
    t = _make_transport(handler)
    with pytest.raises(CyberLogAuthError):
        t.validate()


def test_validate_network_error():
    def handler(req): raise httpx.ConnectError("nope")
    t = _make_transport(handler)
    with pytest.raises(CyberLogTransportError):
        t.validate()


def test_send_batch_success():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.content.decode())
        return httpx.Response(202, json={"accepted": 1, "queue_depth": 0})

    t = _make_transport(handler)
    entry = CyberLogEntry(level="info", message="hi", project="p")
    result = t.send_batch([entry])
    assert result.status is SendStatus.OK
    assert result.accepted == 1
    assert captured["body"]["logs"][0]["message"] == "hi"


def test_send_batch_401_marks_auth_fail():
    def handler(req): return httpx.Response(401, json={"detail": "bad"})
    t = _make_transport(handler)
    r = t.send_batch([CyberLogEntry(level="info", message="x", project="p")])
    assert r.status is SendStatus.AUTH_FAIL


def test_send_batch_413_marks_split():
    def handler(req): return httpx.Response(413, json={"detail": "too big"})
    t = _make_transport(handler)
    r = t.send_batch([CyberLogEntry(level="info", message="x", project="p")])
    assert r.status is SendStatus.SPLIT


def test_send_batch_5xx_marks_retry():
    def handler(req): return httpx.Response(503, json={"detail": "redis down"})
    t = _make_transport(handler)
    r = t.send_batch([CyberLogEntry(level="info", message="x", project="p")])
    assert r.status is SendStatus.RETRY


def test_send_batch_network_error_marks_retry():
    def handler(req): raise httpx.ConnectError("nope")
    t = _make_transport(handler)
    r = t.send_batch([CyberLogEntry(level="info", message="x", project="p")])
    assert r.status is SendStatus.RETRY


def test_empty_batch_is_no_op():
    def handler(req): raise AssertionError("should not hit network")
    t = _make_transport(handler)
    r = t.send_batch([])
    assert r.status is SendStatus.OK
    assert r.accepted == 0
