"""
Exception hierarchy.

Catching `CyberLogError` covers every error this library ever raises.
Library-internal failures (network blips, queue full, etc.) are swallowed
and logged via the stdlib `logging` module — they never propagate to the
host application's call stack so a logging outage can't take down the app.
"""
from __future__ import annotations


class CyberLogError(Exception):
    """Base class for every exception raised by cyberlog."""


class CyberLogConfigurationError(CyberLogError):
    """Raised when CyberLogCore is constructed with invalid arguments."""


class CyberLogAuthError(CyberLogError):
    """
    Raised when the API key is rejected by the server (HTTP 401).

    Surfaced from the constructor when `validate_on_init=True` (default) so
    misconfigured deployments fail fast at startup instead of silently
    dropping logs in production.
    """


class CyberLogTransportError(CyberLogError):
    """Raised for unrecoverable HTTP/transport problems during validation."""
