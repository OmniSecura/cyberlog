# cyberlog

[![PyPI](https://img.shields.io/pypi/v/cyberlog.svg)](https://pypi.org/project/cyberlog/)
[![Python](https://img.shields.io/pypi/pyversions/cyberlog.svg)](https://pypi.org/project/cyberlog/)
[![License](https://img.shields.io/pypi/l/cyberlog.svg)](https://github.com/OmniSecura/cyberlog/blob/main/LICENSE)

Official Python SDK for [**CyberCore** Logging](https://github.com/OmniSecura/CyberCore).
Drop it into any project, authenticate with your organization's API key, and start
shipping structured logs to your dashboard with a single import.

* **One-import setup** — `from cyberlog import CyberLogCore` and you're done.
* **Non-blocking** — `log.*` calls hand off to a background thread, never block your app.
* **Batched & resilient** — automatic batching, exponential backoff, 413-split, drop-on-auth-failure.
* **Structured** — every call takes free-form `**fields` that show up in the dashboard.
* **Tiny dependency footprint** — just `httpx`.
* **Typed** — full type hints, ships with `py.typed`.

---

## Installation

```bash
pip install cyberlog
```

Requires Python 3.9+.

## Quickstart

```python
from cyberlog import CyberLogCore

log = CyberLogCore(
    api_key="ccl_your_key_here",   # generate in the CyberCore dashboard
    project="my-backend",
)

log.info("User logged in", user_id="abc123")
log.warning("Rate limit approaching", endpoint="/api/v1/scan", remaining=12)
log.error("Payment failed", order_id="xyz", amount=99.99)
```

That's it — open the **Logs** tab of your organization in CyberCore and the
events show up in real time.

## Configuration

You can pass values directly or set environment variables:

| Argument         | Env var                | Default                                  |
|------------------|------------------------|------------------------------------------|
| `api_key`        | `CYBERLOG_API_KEY`     | *required*                               |
| `project`        | —                      | *required*                               |
| `api_url`        | `CYBERLOG_API_URL`     | `https://logs.omnisecura.pl/api/v1`      |

Useful tuning knobs (defaults work for 99% of cases):

```python
log = CyberLogCore(
    api_key=...,
    project=...,
    batch_size=100,          # max entries per HTTP request
    flush_interval=2.0,      # seconds the worker waits for a partial batch
    max_queue_size=10_000,   # dropped-oldest backpressure threshold
    max_retries=5,           # before giving up on a batch
    timeout=10.0,            # per-request HTTP timeout
    console=False,           # also print every log to stdout (dev mode)
    validate_on_init=True,   # hit /auth/validate at startup
)
```

## Sticky context with `bind()`

Re-emitting the same fields on every line gets tedious — `bind()` returns a
child logger that automatically includes a base set of fields:

```python
req_log = log.bind(request_id="r-42", user_id="u-7")
req_log.info("Request received")
req_log.info("Request completed", status=200)
```

Both lines arrive with `request_id="r-42"` and `user_id="u-7"` attached.
Per-call fields override bound ones if they collide. Child loggers share the
parent's network resources, so creating many of them is cheap.

## Log levels

Standard set, matching the Python `logging` module's vocabulary:

```python
log.debug("...")     # noisy diagnostics
log.info("...")      # ordinary events
log.warning("...")   # something unusual but not broken (alias: log.warn)
log.error("...")     # something broke
log.critical("...")  # system is on fire
```

Or the generic form: `log.log("info", "message", **fields)`.

## Lifecycle

Cyberlog installs an `atexit` hook that flushes the in-memory queue on
normal interpreter shutdown, so most apps don't need to do anything.

For workers that fork, drain on receipt of SIGTERM, or run inside test
suites, you can flush explicitly:

```python
log.flush(timeout=5.0)   # block until the queue drains
log.close()              # flush + stop the background thread
```

Or use it as a context manager:

```python
with CyberLogCore(api_key=..., project=...) as log:
    log.info("Doing work")
```

## What gets sent

Each `log.*` call becomes one entry in the next outbound batch:

```json
{
  "level":     "error",
  "message":   "Payment failed",
  "project":   "my-backend",
  "timestamp": "2026-05-19T14:32:08.221+00:00",
  "fields":    { "order_id": "xyz", "amount": 99.99 }
}
```

`timestamp` is generated locally in UTC at the time of the call.

## Error handling

Cyberlog never crashes your app over a network blip:

* Bad / revoked API key (HTTP 401) at runtime → the buffer logs a single
  warning to the stdlib `logging` module and silently drops further entries
  until the process restarts with a working key.
* Server unreachable → batches are retried with exponential backoff
  (1s, 2s, 4s, … capped at 30s, up to `max_retries` times) and then dropped.
* Queue full → the oldest entry is evicted to make room for the newest.

The constructor IS allowed to raise:

* `CyberLogConfigurationError` — missing/invalid arguments.
* `CyberLogAuthError` — server returned 401 during the startup probe.
* `CyberLogTransportError` — server unreachable during the startup probe.

Set `validate_on_init=False` if you'd rather fail late than fail early.

## Local development

For local CyberCore deployments, point at your dev instance:

```python
log = CyberLogCore(
    api_key="ccl_dev_key",
    project="my-backend",
    api_url="http://localhost:8083/api/v1",
)
```

Or set `CYBERLOG_API_URL` in your shell.

## License

[MIT](LICENSE) — © OmniSecura.
