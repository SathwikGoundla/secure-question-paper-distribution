"""
Phase 6E-2 — a minimal, in-process, fixed-window rate limiter.

Used ONLY by app/api/v1/auth.py, ONLY for POST /auth/login and
POST /auth/otp/verify (app/config.py: AUTH_LOGIN_RATE_LIMIT /
AUTH_LOGIN_RATE_WINDOW_SECONDS, AUTH_OTP_RATE_LIMIT /
AUTH_OTP_RATE_WINDOW_SECONDS). No other endpoint is rate-limited by
this phase — a general-purpose, every-endpoint limiter was explicitly
out of scope.

Deliberately NOT a general-purpose framework, and deliberately NOT
backed by Redis/Memcached/any external store: a single ~100-line
class, stdlib only, consistent with this project's B.Tech-scope,
single-instance deployment model (see PROJECT_STATE.md Section 23 for
the Phase 6E-2 record of this decision).

DOCUMENTED LIMITATION — read before deploying with more than one
worker process: state lives in this Python process's memory only. If
this application is ever run as `uvicorn ... --workers N` (N > 1), or
behind a load balancer fanning out to multiple replicas, each
process/replica holds its OWN independent counters, so the effective
limit becomes (configured limit x number of processes/replicas), not
a true global limit. This module does not claim otherwise. For the
project's current single-process deployment, this is exact, not
approximate.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class _Window:
    window_start: float
    count: int


class FixedWindowRateLimiter:
    """
    Thread-safe fixed-window request counter, keyed by an arbitrary
    caller-supplied string (the "client identity" — see auth.py for
    how that key is built for login vs. OTP).

    allow(key) increments and returns True if this call is within the
    configured limit for key's CURRENT window, or False if the caller
    should be rejected. A rejected call does NOT consume a slot (so
    repeatedly hammering a locked-out key does not itself do anything
    beyond continuing to be rejected).
    """

    # Bounds total memory regardless of how many distinct keys are
    # seen (e.g. an attacker trying many different usernames from one
    # IP). When the tracked-key count reaches this threshold, a sweep
    # removes every key whose window has already fully expired before
    # the new key is recorded. No background thread, no external
    # store — a sweep only ever runs on the thread that happens to
    # trigger it, bounded by the work of one dict pass.
    _MAX_TRACKED_KEYS = 10_000

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._limit = limit
        self._window_seconds = float(window_seconds)
        # Overridable by tests (monkeypatch.setattr(limiter, "_time_func", fake_clock))
        # to exercise window-expiry behaviour deterministically, without
        # real sleeps. Production code always uses the default
        # time.monotonic — never wall-clock time.time(), which can jump
        # backwards (NTP adjustment, DST) and would make the window
        # math unreliable.
        self._time_func = time_func
        self._lock = threading.Lock()
        self._windows: dict[str, _Window] = {}

    def _sweep_expired_locked(self, now: float) -> None:
        expired_keys = [
            k for k, w in self._windows.items() if now - w.window_start >= self._window_seconds
        ]
        for k in expired_keys:
            del self._windows[k]

    def allow(self, key: str) -> bool:
        now = self._time_func()
        with self._lock:
            if len(self._windows) >= self._MAX_TRACKED_KEYS:
                self._sweep_expired_locked(now)

            window = self._windows.get(key)
            if window is None or now - window.window_start >= self._window_seconds:
                # New key, or this key's previous window has fully
                # elapsed: start a fresh window, this call counts as 1.
                self._windows[key] = _Window(window_start=now, count=1)
                return True

            if window.count < self._limit:
                window.count += 1
                return True

            return False

    def retry_after_seconds(self, key: str) -> int:
        """
        Best-effort whole seconds until key's current window resets.
        Returns 0 if the key is not currently tracked (nothing to wait
        for — the next call will simply start a fresh window). Never
        fabricates a value: this is computed directly from the same
        window_start/window_seconds allow() itself uses, not a
        separately-guessed constant.
        """
        now = self._time_func()
        with self._lock:
            window = self._windows.get(key)
            if window is None:
                return 0
            remaining = self._window_seconds - (now - window.window_start)
            return max(0, math.ceil(remaining))

    def reset(self) -> None:
        """Test-only convenience: clears all tracked state."""
        with self._lock:
            self._windows.clear()
