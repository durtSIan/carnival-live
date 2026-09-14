from __future__ import annotations

import copy
import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Hashable, TypeVar


T = TypeVar("T")


@dataclass
class _Entry:
    value: object
    expires_at: float
    stale_until: float


class SharedResponseCache:
    """Small process-wide TTL cache with one loader per cache key at a time."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
        report_every: int = 100,
    ):
        self._clock = clock
        self._logger = logger or logging.getLogger(__name__)
        self._report_every = report_every
        self._entries: dict[Hashable, _Entry] = {}
        self._inflight: dict[Hashable, threading.Event] = {}
        self._lock = threading.Lock()
        self._stats: Counter[str] = Counter()

    def get_or_load(
        self,
        key: Hashable,
        loader: Callable[[], T],
        *,
        ttl_seconds: float,
        stale_seconds: float,
    ) -> T:
        while True:
            now = self._clock()
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None and now < entry.expires_at:
                    self._record("hits")
                    return copy.deepcopy(entry.value)

                event = self._inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self._inflight[key] = event
                    self._record("misses")
                    is_loader = True
                else:
                    self._record("waits")
                    is_loader = False

            if is_loader:
                break
            event.wait()

        try:
            value = loader()
        except Exception as exc:
            with self._lock:
                now = self._clock()
                entry = self._entries.get(key)
                stale = entry is not None and now < entry.stale_until
                if stale:
                    self._record("stale_served")
                    value = copy.deepcopy(entry.value)
                self._finish_load(key, event)
            if stale:
                self._logger.warning(
                    "Serving stale Play Cricket data for %s after upstream failure: %s",
                    key,
                    exc,
                )
                return value  # type: ignore[return-value]
            raise

        with self._lock:
            now = self._clock()
            self._entries[key] = _Entry(
                value=copy.deepcopy(value),
                expires_at=now + max(0, ttl_seconds),
                stale_until=now + max(ttl_seconds, stale_seconds),
            )
            self._record("loads")
            self._finish_load(key, event)
            self._discard_expired(now)
        return copy.deepcopy(value)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def _finish_load(self, key: Hashable, event: threading.Event) -> None:
        self._inflight.pop(key, None)
        event.set()

    def _discard_expired(self, now: float) -> None:
        if len(self._entries) <= 512:
            return
        self._entries = {
            key: entry
            for key, entry in self._entries.items()
            if now < entry.stale_until
        }

    def _record(self, name: str) -> None:
        self._stats[name] += 1
        total = sum(self._stats.values())
        if self._report_every and total % self._report_every == 0:
            self._logger.info(
                "Play Cricket cache stats: hits=%d misses=%d loads=%d waits=%d stale=%d",
                self._stats["hits"],
                self._stats["misses"],
                self._stats["loads"],
                self._stats["waits"],
                self._stats["stale_served"],
            )
