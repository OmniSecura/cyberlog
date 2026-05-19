"""
Internal data shapes.

`CyberLogEntry` is what `CyberLogCore._log()` builds and what the buffer
hands to the transport. Users never construct this directly — they only
see it if they enable console echo for local debugging.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    """ISO-8601 with explicit UTC offset — what the backend expects."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CyberLogEntry:
    """
    One log line on its way to the server.

    Fields mirror the JSON the backend's POST /api/v1/ingest accepts so the
    transport can serialise this dataclass with a trivial `to_dict()` call.
    """

    level: str            # debug | info | warning | error | critical
    message: str
    project: str
    timestamp: str = field(default_factory=_utc_now_iso)
    fields: dict[str, Any] = field(default_factory=dict)

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "level":     self.level,
            "message":   self.message,
            "project":   self.project,
            "timestamp": self.timestamp,
            "fields":    self.fields,
        }

    # ── Pretty repr for console-echo / debugging ─────────────────────────────

    def __repr__(self) -> str:
        extra = ""
        if self.fields:
            extra = " " + " ".join(f"{k}={v!r}" for k, v in self.fields.items())
        return f"[{self.level.upper():<8}] {self.timestamp} {self.project}: {self.message}{extra}"
