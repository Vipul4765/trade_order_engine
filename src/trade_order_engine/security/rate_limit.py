"""Thread-safe in-memory sliding-window rate limiter."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    """Limits requests per key over a rolling time window (default: 60s)."""

    def __init__(
        self,
        max_requests: int,
        *,
        window_seconds: float = 60.0,
        max_tracked_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._max_tracked_keys = max_tracked_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = {}

    @property
    def enabled(self) -> bool:
        return self.max_requests > 0

    def allow(self, key: str) -> tuple[bool, int]:
        """Record a request for `key` if allowed.

        Returns `(allowed, retry_after_seconds)`.
        """
        if not self.enabled:
            return True, 0

        now = self._clock()
        cutoff = now - self.window_seconds

        with self._lock:
            if len(self._buckets) >= self._max_tracked_keys and key not in self._buckets:
                self._prune_stale(cutoff)

            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                retry_after = max(1, math.ceil(self.window_seconds - (now - bucket[0])))
                return False, retry_after

            bucket.append(now)
            return True, 0

    def _prune_stale(self, cutoff: float) -> None:
        stale_keys = [
            bucket_key
            for bucket_key, timestamps in self._buckets.items()
            if not timestamps or timestamps[-1] <= cutoff
        ]
        for bucket_key in stale_keys:
            del self._buckets[bucket_key]
