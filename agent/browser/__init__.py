"""Browser module for OpenCLI integration and browser lock management."""

from .browser_lock import (
    BrowserLock,
    BrowserLockTimeoutError,
    get_browser_lock,
)
from .cdp_client import (
    CDPClient,
    CDPCommandError,
    CDPConnectionError,
    CDPError,
)
from .opencli_client import OpenCLIClient

__all__ = [
    "OpenCLIClient",
    "BrowserLock",
    "BrowserLockTimeoutError",
    "get_browser_lock",
    "CDPClient",
    "CDPError",
    "CDPConnectionError",
    "CDPCommandError",
]
