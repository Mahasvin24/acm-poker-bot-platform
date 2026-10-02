from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress

from poker_bot_platform.integration.runtime import HeadlessGameplayRuntime
from poker_bot_platform.integration.services import TournamentRegistry

logger = logging.getLogger(__name__)

MonotonicClock = Callable[[], float]


class GameplayScheduler:
    """Lifespan-owned clock and deadline driver for known tournaments.

    The registry deliberately owns only tournaments touched in this process. A
    deployment restart therefore needs an API/admin access to restore a persisted
    tournament before this scheduler can discover and drive it.
    """

    def __init__(
        self,
        tournaments: TournamentRegistry,
        gameplay: HeadlessGameplayRuntime,
        *,
        poll_interval_seconds: float = 0.25,
        monotonic: MonotonicClock = time.monotonic,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        self._tournaments = tournaments
        self._gameplay = gameplay
        self._poll_interval = poll_interval_seconds
        self._monotonic = monotonic
        self._last_level_tick: dict[str, float] = {}
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._last_level_tick.clear()
        self._task = asyncio.create_task(self._run(), name="poker-gameplay-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def run_once(self, *, now: float | None = None) -> None:
        """Advance one deterministic polling cycle; public for focused tests."""

        current = self._monotonic() if now is None else now
        tournament_ids = await self._tournaments.known_tournament_ids()
        active_ids = set(tournament_ids)
        for tournament_id in tuple(self._last_level_tick):
            if tournament_id not in active_ids:
                self._last_level_tick.pop(tournament_id, None)
        await asyncio.gather(
            *(self._service_tournament(tournament_id, current) for tournament_id in tournament_ids)
        )

    async def _run(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self._poll_interval)

    async def _service_tournament(self, tournament_id: str, now: float) -> None:
        previous = self._last_level_tick.setdefault(tournament_id, now)
        if now < previous:
            previous = now
            self._last_level_tick[tournament_id] = now
        elapsed_seconds = int(now - previous)
        if elapsed_seconds:
            # Consume the interval before the durable tick. This prevents an
            # ambiguous post-commit failure from applying the same seconds twice
            # and freezes, rather than catches up, time lost to a database outage.
            self._last_level_tick[tournament_id] = previous + elapsed_seconds
            try:
                coordinator = await self._tournaments.get(tournament_id)
                await coordinator.tick(elapsed_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("tournament clock update failed", extra={"id": tournament_id})
        try:
            await self._gameplay.synchronize(tournament_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "tournament gameplay synchronization failed", extra={"id": tournament_id}
            )
