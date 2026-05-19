"""
In-memory buffer + background flush thread.

Design goals
------------
* `log.info()` MUST NOT block the host application. It enqueues a single
  entry to a bounded queue and returns immediately.
* A daemon thread drains the queue in batches and hands each batch to the
  `Transport`. Retries (with exponential backoff) and 413-split logic live
  here so the transport layer stays stateless.
* Graceful shutdown via `flush()` (synchronous) and `close()` (stops the
  thread). An `atexit` hook is registered by the core so logs aren't lost
  when the host process exits cleanly.

Bounded queue
-------------
We cap the queue at `max_queue_size` so a misbehaving consumer can't grow
memory unbounded. When the cap is reached new entries are dropped and a
warning is emitted via the stdlib logger — this matches what Sentry / DD
agents do under back-pressure.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import TYPE_CHECKING

from .models import CyberLogEntry

if TYPE_CHECKING:
    from .transport import Transport

from .transport import SendStatus  # noqa: E402   (avoid TYPE_CHECKING cycle)

_log = logging.getLogger("cyberlog.buffer")


class Buffer:
    def __init__(
        self,
        transport: "Transport",
        *,
        batch_size: int = 100,
        flush_interval: float = 2.0,
        max_queue_size: int = 10_000,
        max_retries: int = 5,
        backoff_initial: float = 1.0,
        backoff_max: float = 30.0,
        console: bool = False,
    ) -> None:
        self._transport = transport
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._console = console

        self._queue: queue.Queue[CyberLogEntry] = queue.Queue(maxsize=max_queue_size)

        # Set when the host wants the thread to stop after draining.
        self._stopping = threading.Event()
        # Set when the thread has fully exited.
        self._stopped  = threading.Event()
        # Auth failures permanently disable the buffer so we don't burn CPU
        # spinning through retries on a dead key.
        self._auth_failed = False

        # Lock used by flush() to coordinate with the worker.
        self._idle_lock = threading.Lock()

        self._thread = threading.Thread(
            target=self._run,
            name="cyberlog-flush",
            daemon=True,
        )
        self._thread.start()

    # ── Public API ───────────────────────────────────────────────────────────

    def add(self, entry: CyberLogEntry) -> None:
        """Enqueue an entry. Never blocks — drops the oldest item if full."""
        if self._auth_failed:
            return

        if self._console:
            # Stable print for local debugging; uses repr() of the entry.
            print(entry, flush=True)

        try:
            self._queue.put_nowait(entry)
        except queue.Full:
            # Drop oldest, then enqueue the newest — keeps recent context.
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(entry)
            except queue.Full:
                _log.warning("cyberlog: queue still full — dropping entry.")

    def flush(self, timeout: float = 5.0) -> bool:
        """
        Block until the queue is drained or `timeout` seconds pass.

        Returns True if the queue is empty, False on timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.empty():
                # Re-check after a tick to make sure the worker isn't mid-send.
                with self._idle_lock:
                    if self._queue.empty():
                        return True
            time.sleep(0.05)
        return False

    def close(self, timeout: float = 5.0) -> None:
        """Flush, then stop the background thread."""
        self.flush(timeout=timeout)
        self._stopping.set()
        self._thread.join(timeout=timeout)
        self._stopped.set()

    # ── Worker ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stopping.is_set():
            batch = self._collect_batch()
            if not batch:
                continue
            self._send_with_retries(batch)

        # Drain remaining entries on shutdown.
        leftover = self._collect_batch(drain=True)
        if leftover:
            self._send_with_retries(leftover)

    def _collect_batch(self, *, drain: bool = False) -> list[CyberLogEntry]:
        """
        Pull up to `batch_size` entries off the queue.

        Blocks up to `flush_interval` for the first entry so we don't busy-spin
        when the application is idle. Subsequent entries are pulled non-blocking.
        """
        batch: list[CyberLogEntry] = []
        try:
            first = self._queue.get(timeout=self._flush_interval)
            batch.append(first)
            self._queue.task_done()
        except queue.Empty:
            return batch

        limit = None if drain else self._batch_size
        while limit is None or len(batch) < limit:
            try:
                batch.append(self._queue.get_nowait())
                self._queue.task_done()
            except queue.Empty:
                break
        return batch

    def _send_with_retries(self, batch: list[CyberLogEntry]) -> None:
        """Send `batch`, handling split / retry / drop semantics."""
        if not batch:
            return

        with self._idle_lock:
            self._send_recursive(batch, attempt=0)

    def _send_recursive(self, batch: list[CyberLogEntry], *, attempt: int) -> None:
        result = self._transport.send_batch(batch)

        if result.status is SendStatus.OK:
            return

        if result.status is SendStatus.AUTH_FAIL:
            self._auth_failed = True
            return

        if result.status is SendStatus.DROP:
            return  # already logged inside transport

        if result.status is SendStatus.SPLIT:
            if len(batch) <= 1:
                _log.warning("cyberlog: single entry rejected as too large — dropping.")
                return
            mid = len(batch) // 2
            self._send_recursive(batch[:mid], attempt=0)
            self._send_recursive(batch[mid:], attempt=0)
            return

        # ── RETRY ──
        if attempt >= self._max_retries:
            _log.warning(
                "cyberlog: gave up on batch of %d after %d retries (%s).",
                len(batch), attempt, result.detail,
            )
            return

        delay = min(self._backoff_initial * (2 ** attempt), self._backoff_max)
        # If the host is shutting down, don't bother sleeping.
        if self._stopping.wait(timeout=delay):
            return
        self._send_recursive(batch, attempt=attempt + 1)
