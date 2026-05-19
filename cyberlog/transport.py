"""
HTTP transport — turns a batch of CyberLogEntry into a POST to the server.

Responsibilities:
    * Build the `Authorization: Bearer ccl_...` header.
    * Serialise the batch and POST it to `<api_url>/ingest`.
    * Translate HTTP responses into transport-level outcomes the buffer
      knows how to handle (success / retry / split / drop).
    * Implement validation against `/auth/validate` so the constructor can
      fail fast on a bad key.

The transport itself does NO retrying — it just classifies the response
and lets the caller (buffer thread or constructor) decide what to do
next. That keeps the retry policy in ONE place (`buffer.py`) instead of
scattering it across modules.
"""
from __future__ import annotations

import enum
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass

import httpx

from ._version import __version__
from .exceptions import (
    CyberLogAuthError,
    CyberLogTransportError,
)
from .models import CyberLogEntry

_log = logging.getLogger("cyberlog.transport")

USER_AGENT = f"cyberlog-python/{__version__}"


# ─── Outcome of a single send attempt ─────────────────────────────────────────

class SendStatus(enum.Enum):
    OK         = "ok"          # batch accepted by the server (HTTP 202)
    DROP       = "drop"        # permanent client error — discard the batch
    SPLIT      = "split"       # batch too large — caller should halve and resend
    RETRY      = "retry"       # transient — caller should back off and retry
    AUTH_FAIL  = "auth_fail"   # key was revoked/expired — stop sending


@dataclass
class SendResult:
    status:  SendStatus
    detail:  str = ""
    accepted: int = 0


# ─── Transport ────────────────────────────────────────────────────────────────

class Transport:
    """Thin wrapper around an `httpx.Client` configured for cyberlog."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        timeout: float = 10.0,
    ) -> None:
        # Strip trailing slash so `<base>/ingest` is correct whether the user
        # passed `.../api/v1` or `.../api/v1/`.
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent":    USER_AGENT,
                "Content-Type":  "application/json",
            },
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def validate(self) -> dict:
        """
        One-shot startup probe: hit `/auth/validate` and return the org metadata.

        Raises:
            CyberLogAuthError      — 401 from the server (bad/revoked key).
            CyberLogTransportError — connectivity error or non-2xx other than 401.
        """
        url = f"{self.api_url}/auth/validate"
        try:
            res = self._client.get(url)
        except httpx.HTTPError as exc:
            raise CyberLogTransportError(
                f"Could not reach cyberlog at {url}: {exc}"
            ) from exc

        if res.status_code == 401:
            raise CyberLogAuthError(
                _extract_detail(res, default="API key was rejected (401).")
            )
        if not res.is_success:
            raise CyberLogTransportError(
                f"Unexpected HTTP {res.status_code} from {url}: "
                f"{_extract_detail(res, default=res.text[:200])}"
            )

        try:
            return res.json()
        except ValueError as exc:
            raise CyberLogTransportError(
                f"Server returned non-JSON during validation: {exc}"
            ) from exc

    def send_batch(self, entries: Iterable[CyberLogEntry]) -> SendResult:
        """Send one batch and return a structured outcome — never raises."""
        payload = {"logs": [e.to_dict() for e in entries]}
        if not payload["logs"]:
            return SendResult(SendStatus.OK, accepted=0)

        url = f"{self.api_url}/ingest"
        try:
            res = self._client.post(url, content=json.dumps(payload))
        except httpx.HTTPError as exc:
            _log.warning("cyberlog: network error talking to %s: %s", url, exc)
            return SendResult(SendStatus.RETRY, detail=str(exc))

        # ── 2xx ──
        if res.is_success:
            try:
                body = res.json()
            except ValueError:
                body = {}
            return SendResult(
                SendStatus.OK,
                accepted=int(body.get("accepted", len(payload["logs"]))),
            )

        # ── 4xx / 5xx classification ──
        code = res.status_code
        detail = _extract_detail(res)

        if code == 401:
            _log.error("cyberlog: API key rejected (401). Logs are being dropped.")
            return SendResult(SendStatus.AUTH_FAIL, detail=detail)

        if code == 400:
            _log.warning("cyberlog: server rejected batch (400): %s", detail)
            return SendResult(SendStatus.DROP, detail=detail)

        if code == 413:
            return SendResult(SendStatus.SPLIT, detail=detail)

        if 500 <= code < 600 or code == 503:
            _log.warning("cyberlog: transient server error (%s): %s", code, detail)
            return SendResult(SendStatus.RETRY, detail=detail)

        # Any other 4xx is unrecoverable — drop and move on.
        _log.warning("cyberlog: unexpected HTTP %s: %s", code, detail)
        return SendResult(SendStatus.DROP, detail=detail)

    def close(self) -> None:
        self._client.close()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_detail(response: httpx.Response, *, default: str = "") -> str:
    """Pull `detail` out of a FastAPI-style error body, or fall back to text."""
    try:
        data = response.json()
        if isinstance(data, dict) and "detail" in data:
            return str(data["detail"])
    except ValueError:
        pass
    return (response.text[:200] if response.text else default)
