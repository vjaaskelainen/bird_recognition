"""In-memory owner session store backing the same-origin session cookie."""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from threading import Lock

SESSION_COOKIE = "br_session"
IDLE_SECONDS = 12 * 60 * 60


class SessionStore:
    """Hold hashed session tokens with idle expiry; nothing is persisted."""

    def __init__(
        self,
        idle_seconds: float = IDLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._idle_seconds = idle_seconds
        self._clock = clock
        self._sessions: dict[str, float] = {}
        self._lock = Lock()

    def create(self) -> str:
        """Issue a new 256-bit token; only its digest is retained."""
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge()
            self._sessions[_digest(token)] = self._clock()
        return token

    def validate(self, token: str | None) -> bool:
        """Return whether the token is live, refreshing its idle timer."""
        if not token:
            return False
        digest = _digest(token)
        with self._lock:
            self._purge()
            if digest not in self._sessions:
                return False
            self._sessions[digest] = self._clock()
            return True

    def revoke(self, token: str | None) -> None:
        """Invalidate one token; unknown tokens are ignored."""
        if not token:
            return
        with self._lock:
            self._sessions.pop(_digest(token), None)

    def clear(self) -> None:
        """Drop every session."""
        with self._lock:
            self._sessions.clear()

    def _purge(self) -> None:
        now = self._clock()
        expired = [
            digest
            for digest, seen in self._sessions.items()
            if now - seen > self._idle_seconds
        ]
        for digest in expired:
            del self._sessions[digest]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
