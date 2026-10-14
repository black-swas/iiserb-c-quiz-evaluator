"""Process hardening, constant-time token comparison and a small rate limiter."""
import hmac
import logging
import os
import sys
import threading
import time
from collections import deque
from typing import Deque, Dict, Iterable, Tuple

logger = logging.getLogger("iiserb.security")

PR_SET_DUMPABLE = 4
SECRET_ENV_VARS = ("ANTHROPIC_API_KEY", "API_AUTH_TOKEN")


def harden_process() -> bool:
    """Make this process non-dumpable (Linux).

    Student programs run under the same Unix user as the web server, so by default they could
    read /proc/<server-pid>/environ (which contains the API key injected by the platform).
    A non-dumpable process has its /proc/<pid>/* files owned by root, which closes that path.
    Children created afterwards are unaffected: exec() makes them dumpable again.
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        ok = libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
        if not ok:
            logger.warning("prctl(PR_SET_DUMPABLE) failed: errno=%s", ctypes.get_errno())
        return ok
    except Exception as exc:  # pragma: no cover - platform specific
        logger.warning("Could not harden process: %s", exc)
        return False


def scrub_secret_env(names: Iterable[str] = SECRET_ENV_VARS) -> None:
    """Remove secrets from os.environ after they were copied into settings."""
    for name in names:
        os.environ.pop(name, None)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class SlidingWindowRateLimiter:
    """In-memory limiter. Valid because the service runs a single worker process."""

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: float) -> Tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = int(max(1, window_seconds - (now - hits[0])))
                return False, retry_after
            hits.append(now)
            if len(self._hits) > 5000:  # keep memory bounded
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True, 0
