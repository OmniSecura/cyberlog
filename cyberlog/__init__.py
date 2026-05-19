"""
cyberlog — official Python SDK for CyberCore Logging.

Quick start:

    from cyberlog import CyberLogCore

    log = CyberLogCore(api_key="ccl_...", project="my-backend")
    log.info("User logged in", user_id="abc123")
    log.error("Payment failed", order_id="xyz", amount=99.99)

Logs are buffered in-memory and flushed asynchronously by a background
thread, so calls to log.* never block your application.
"""
from ._version import __version__
from .core import CyberLogCore
from .exceptions import (
    CyberLogAuthError,
    CyberLogConfigurationError,
    CyberLogError,
    CyberLogTransportError,
)
from .models import CyberLogEntry

__all__ = [
    "__version__",
    "CyberLogCore",
    "CyberLogEntry",
    "CyberLogError",
    "CyberLogAuthError",
    "CyberLogConfigurationError",
    "CyberLogTransportError",
]
