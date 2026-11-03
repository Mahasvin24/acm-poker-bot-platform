from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress

from poker_bot_platform.integration.runtime import MatchRuntime
from poker_bot_platform.match import MatchRegistry

logger = logging.getLogger(__name__)

MonotonicClock = Callable[[], float]


class GameplayScheduler:
    """Lifespan-owned driver for match clocks, deadlines, pacing, and bot turns.

    Each match is driven in its own background task so a slow bot at one table never
    delays another match. ``wake`` lets commands skip the remaining poll interval.
    """

    def __init__(
        self,
        registry: MatchRegistry,
        runtime: MatchRuntime,
        *,
        poll_interval_seconds: float = 0.25,
        monotonic: MonotonicClock = time.monotonic,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        self._registry = registry
        self._runtime = runtime
        self._poll_interval = poll_interval_seconds
        self._monotonic = monotonic
        self._last_level_tick: dict[str, float] = {}
        self._drives: dict[str, asyncio.Task[None]] = {}
        self._task: asyncio.Task[None] | None = None
        self._wake: asyncio.Event | None = None
        runtime.set_wake_callback(self.wake)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def wake(self) -> None:
        if self._wake is not None:
            self._wake.set()

    async def start(self) -> None:
        if self.running:
            return
        self._last_level_tick.clear()
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="poker-gameplay-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        drives = tuple(self._drives.values())
        self._drives.clear()
        for pending in (task, *drives):
            if pending is None:
                continue
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending

    async def run_once(self, *, now: float | None = None) -> None:
        """Advance one polling cycle and wait for its drives; public for focused tests."""

        await self._dispatch(now)
        drives = tuple(self._drives.values())
        if drives:
            await asyncio.gather(*drives, return_exceptions=True)

    async def _dispatch(self, now: float | None = None) -> None:
        current = self._monotonic() if now is None else now
        try:
            await self._registry.discover_active_matches()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep servicing already known matches while discovery is unavailable,
            # for example during a database outage.
            logger.exception("active match discovery failed")
        match_ids = await self._registry.known_match_ids()
        for match_id in tuple(self._last_level_tick):
            if match_id not in match_ids:
                self._last_level_tick.pop(match_id, None)
        for match_id in match_ids:
            await self._tick_level(match_id, current)
            task = self._drives.get(match_id)
            if task is None or task.done():
                self._drives[match_id] = asyncio.create_task(
                    self._drive(match_id), name=f"poker-drive-{match_id}"
                )

    async def _run(self) -> None:
        assert self._wake is not None
        while True:
            await self._dispatch()
            self._wake.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval)

    async def _tick_level(self, match_id: str, now: float) -> None:
        previous = self._last_level_tick.setdefault(match_id, now)
        if now < previous:
            self._last_level_tick[match_id] = now
            return
        elapsed_seconds = int(now - previous)
        if not elapsed_seconds:
            return
        # Consume the interval before the durable tick so an ambiguous failure cannot
        # apply the same seconds twice; time lost to an outage is frozen, not replayed.
        self._last_level_tick[match_id] = previous + elapsed_seconds
        try:
            coordinator = await self._registry.get(match_id)
            await coordinator.tick(elapsed_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("match clock update failed", extra={"id": match_id})

    async def _drive(self, match_id: str) -> None:
        try:
            await self._runtime.drive(match_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("match gameplay drive failed", extra={"id": match_id})
