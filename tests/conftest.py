"""
Shared pytest helpers.

Most tests use a `FakeTransport` so we never touch the network. It records
every batch it would have sent and returns scripted outcomes so we can
exercise the retry / split / drop branches in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pytest

from cyberlog.models import CyberLogEntry
from cyberlog.transport import SendResult, SendStatus


@dataclass
class FakeTransport:
    # Scripted outcomes for successive send_batch calls; defaults to OK forever.
    scripted: list[SendResult] = field(default_factory=list)
    # All batches the buffer handed us, in order.
    sent:     list[list[CyberLogEntry]] = field(default_factory=list)
    # Set by tests that want validate() to return a specific payload.
    validate_payload: dict = field(default_factory=lambda: {
        "org_id":   "test-org",
        "key_id":   "test-key",
        "key_name": "test",
    })

    # Cyberlog calls these — match the real Transport's surface area.
    def validate(self) -> dict:
        return self.validate_payload

    def send_batch(self, entries: Iterable[CyberLogEntry]) -> SendResult:
        batch = list(entries)
        self.sent.append(batch)
        if self.scripted:
            return self.scripted.pop(0)
        return SendResult(SendStatus.OK, accepted=len(batch))

    def close(self) -> None:
        pass


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()
