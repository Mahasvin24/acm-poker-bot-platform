from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable


class RateLimitExceeded(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too many attempts; try again later")
        self.retry_after_seconds = retry_after_seconds


class SlidingWindowLimiter:
    """In-process attempt counter. Valid only because v1 runs exactly one worker."""

    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        if max_attempts < 1 or window_seconds <= 0:
            raise ValueError("rate limits must be positive")
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._attempts: dict[str, deque[float]] = {}

    def check(self, key: str) -> None:
        """Raise when ``key`` has exhausted its attempts in the current window."""

        now = self._clock()
        attempts = self._prune(key, now)
        if attempts is not None and len(attempts) >= self._max_attempts:
            retry_after = attempts[0] + self._window - now
            raise RateLimitExceeded(max(1, math.ceil(retry_after)))

    def record(self, key: str) -> None:
        now = self._clock()
        attempts = self._prune(key, now)
        if attempts is None:
            if len(self._attempts) >= self._max_keys:
                self._evict(now)
            attempts = self._attempts.setdefault(key, deque())
        attempts.append(now)

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)

    def _prune(self, key: str, now: float) -> deque[float] | None:
        attempts = self._attempts.get(key)
        if attempts is None:
            return None
        while attempts and attempts[0] <= now - self._window:
            attempts.popleft()
        if not attempts:
            del self._attempts[key]
            return None
        return attempts

    def _evict(self, now: float) -> None:
        for key in tuple(self._attempts):
            self._prune(key, now)
        while len(self._attempts) >= self._max_keys:
            oldest = min(self._attempts, key=lambda item: self._attempts[item][-1])
            del self._attempts[oldest]
