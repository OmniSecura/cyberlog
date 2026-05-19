"""
Public entry point: `CyberLogCore`.

This is the single class users instantiate. Everything else
(`buffer`, `transport`, `models`, `exceptions`) is wiring.

Example
-------

    from cyberlog import CyberLogCore

    log = CyberLogCore(
        api_key="ccl_your_key_here",
        project="my-backend",
    )

    log.info("User logged in", user_id="abc123")
    log.error("Payment failed", order_id="xyz", amount=99.99)

    # Sticky context fields — every log emitted from `req_log` carries
    # `request_id=...` without you having to repeat it.
    req_log = log.bind(request_id="r-42", user_id="u-7")
    req_log.info("Request received")
    req_log.info("Request completed", status=200)

    # Optional explicit shutdown — only needed if you want guaranteed delivery
    # before exit. cyberlog already installs an `atexit` hook that does this
    # automatically for normal process termination.
    log.close()

The library never blocks your application: `log.*` calls hand the entry
to an in-memory queue and return immediately. A daemon thread drains the
queue to the server with batching, backoff, and 413-split handling.
"""
from __future__ import annotations

import atexit
import contextlib
import logging
import os
import weakref
from typing import Any

from .buffer import Buffer
from .exceptions import CyberLogConfigurationError
from .models import CyberLogEntry
from .transport import Transport

_log = logging.getLogger("cyberlog")

DEFAULT_API_URL = "https://logs.omnisecura.pl/api/v1"
ENV_API_URL     = "CYBERLOG_API_URL"
ENV_API_KEY     = "CYBERLOG_API_KEY"

_VALID_LEVELS = ("debug", "info", "warning", "error", "critical")


class CyberLogCore:
    """
    The cyberlog client.

    Parameters
    ----------
    api_key:
        Your organization API key (starts with ``ccl_``). Falls back to the
        ``CYBERLOG_API_KEY`` env var when omitted.
    project:
        Free-form project name attached to every log entry. Required.
    api_url:
        Override the ingest endpoint. Defaults to
        ``https://logs.omnisecura.pl/api/v1`` or the ``CYBERLOG_API_URL`` env var.
    validate_on_init:
        Hit ``/auth/validate`` from the constructor so a bad key fails fast.
        Set to ``False`` in test suites where the network shouldn't be touched.
    console:
        Echo every log line to stdout as well (useful during development).
    batch_size, flush_interval, max_queue_size, max_retries:
        See ``Buffer`` for tuning knobs. Sensible defaults work for 99% of users.

    Raises
    ------
    CyberLogConfigurationError
        Missing api_key / project, or `project` is too long.
    CyberLogAuthError
        Only when ``validate_on_init=True`` and the server returns 401.
    CyberLogTransportError
        Only when ``validate_on_init=True`` and the server is unreachable.
    """

    # ── Construction ─────────────────────────────────────────────────────────

    def __init__(
        self,
        api_key: str | None = None,
        project: str | None = None,
        *,
        api_url: str | None = None,
        validate_on_init: bool = True,
        console: bool = False,
        batch_size: int = 100,
        flush_interval: float = 2.0,
        max_queue_size: int = 10_000,
        max_retries: int = 5,
        timeout: float = 10.0,
        bound_fields: dict[str, Any] | None = None,
        _shared_buffer: Buffer | None = None,
        _shared_transport: Transport | None = None,
    ) -> None:
        # bind() creates child loggers that reuse the parent's buffer/transport,
        # which is signalled via the two underscore-prefixed kwargs above.
        # Users should never pass them directly.
        api_key = api_key or os.getenv(ENV_API_KEY)
        api_url = api_url or os.getenv(ENV_API_URL) or DEFAULT_API_URL

        if not project:
            raise CyberLogConfigurationError(
                "`project` is required — pass the name of your service/app."
            )
        if len(project) > 120:
            raise CyberLogConfigurationError(
                "`project` must be 120 characters or fewer."
            )

        self.project = project
        self._bound_fields: dict[str, Any] = dict(bound_fields or {})

        if _shared_buffer is not None and _shared_transport is not None:
            # Child logger from bind() — reuse parent's I/O resources.
            self._transport = _shared_transport
            self._buffer    = _shared_buffer
            self._owns_io   = False
            self.org_id     = None
            self.key_name   = None
            return

        if not api_key:
            raise CyberLogConfigurationError(
                "`api_key` is required. Pass it explicitly or set the "
                f"{ENV_API_KEY} environment variable."
            )

        self._transport = Transport(api_url=api_url, api_key=api_key, timeout=timeout)

        # Fail fast on a bad key when the caller wants it.
        if validate_on_init:
            info = self._transport.validate()
            self.org_id   = info.get("org_id")
            self.key_name = info.get("key_name")
            _log.debug(
                "cyberlog: authenticated as org=%s key=%s",
                self.org_id, self.key_name,
            )
        else:
            self.org_id = None
            self.key_name = None

        self._buffer = Buffer(
            transport=self._transport,
            batch_size=batch_size,
            flush_interval=flush_interval,
            max_queue_size=max_queue_size,
            max_retries=max_retries,
            console=console,
        )
        self._owns_io = True

        # Best-effort flush at interpreter shutdown. We register a weak
        # reference so a forgotten reference doesn't keep this client alive.
        self_ref = weakref.ref(self)

        def _atexit_flush() -> None:
            inst = self_ref()
            if inst is not None and inst._owns_io:
                with contextlib.suppress(Exception):
                    inst.close(timeout=2.0)

        atexit.register(_atexit_flush)

    # ── Public logging API ───────────────────────────────────────────────────

    def debug    (self, message: str, **fields: Any) -> None: self._log("debug",    message, fields)
    def info     (self, message: str, **fields: Any) -> None: self._log("info",     message, fields)
    def warning  (self, message: str, **fields: Any) -> None: self._log("warning",  message, fields)
    def error    (self, message: str, **fields: Any) -> None: self._log("error",    message, fields)
    def critical (self, message: str, **fields: Any) -> None: self._log("critical", message, fields)

    # Convenient `logging`-module compatible alias.
    warn = warning

    def log(self, level: str, message: str, **fields: Any) -> None:
        """Generic emit — level is checked at runtime."""
        if level not in _VALID_LEVELS:
            raise CyberLogConfigurationError(
                f"Invalid log level {level!r}. "
                f"Expected one of: {', '.join(_VALID_LEVELS)}."
            )
        self._log(level, message, fields)

    def bind(self, **fields: Any) -> CyberLogCore:
        """
        Return a child logger that automatically includes `fields` in every
        emitted entry. Child loggers share the parent's network resources
        and queue, so creating many of them is cheap.
        """
        merged = {**self._bound_fields, **fields}
        return CyberLogCore(
            project=self.project,
            validate_on_init=False,
            bound_fields=merged,
            _shared_buffer=self._buffer,
            _shared_transport=self._transport,
        )

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until the queue is drained or timeout elapses."""
        return self._buffer.flush(timeout=timeout)

    def close(self, timeout: float = 5.0) -> None:
        """Flush the queue and tear down the background thread + HTTP client."""
        if not self._owns_io:
            return
        try:
            self._buffer.close(timeout=timeout)
        finally:
            self._transport.close()

    def __enter__(self) -> CyberLogCore:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ── Internals ────────────────────────────────────────────────────────────

    def _log(self, level: str, message: str, fields: dict[str, Any]) -> None:
        merged = {**self._bound_fields, **fields} if self._bound_fields else fields

        entry = CyberLogEntry(
            level=level,
            message=str(message),
            project=self.project,
            fields=merged,
        )
        self._buffer.add(entry)
