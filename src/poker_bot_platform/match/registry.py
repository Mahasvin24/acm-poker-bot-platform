from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from poker_bot_platform.domain import MatchConfig
from poker_bot_platform.match.codes import generate_join_code
from poker_bot_platform.match.coordinator import MatchCoordinator
from poker_bot_platform.match.models import MatchState
from poker_bot_platform.match.store import JoinCodeConflict, MatchStore, MatchStoreError

logger = logging.getLogger(__name__)

_CODE_ATTEMPTS = 16


class MatchRegistry:
    """Single-process owner and resolver for match coordinators."""

    def __init__(
        self,
        store: MatchStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coordinators: dict[str, MatchCoordinator] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        name: str,
        config: MatchConfig,
        *,
        created_by: str,
    ) -> MatchCoordinator:
        async with self._lock:
            for _ in range(_CODE_ATTEMPTS):
                match_id = f"m-{secrets.token_hex(6)}"
                try:
                    coordinator = await MatchCoordinator.create(
                        match_id,
                        name,
                        config,
                        generate_join_code(),
                        self._store,
                        created_by=created_by,
                        created_at=self._clock(),
                    )
                except JoinCodeConflict:
                    continue
                self._coordinators[match_id] = coordinator
                return coordinator
            raise MatchStoreError("could not allocate a unique join code")

    async def regenerate_code(self, match_id: str, *, actor_id: str) -> MatchState:
        coordinator = await self.get(match_id)
        for _ in range(_CODE_ATTEMPTS):
            try:
                return await coordinator.set_join_code(generate_join_code(), actor_id=actor_id)
            except JoinCodeConflict:
                continue
        raise MatchStoreError("could not allocate a unique join code")

    async def get(self, match_id: str) -> MatchCoordinator:
        coordinator = self._coordinators.get(match_id)
        if coordinator is not None:
            return coordinator
        async with self._lock:
            coordinator = self._coordinators.get(match_id)
            if coordinator is None:
                coordinator = await MatchCoordinator.restore(match_id, self._store)
                self._coordinators[match_id] = coordinator
            return coordinator

    async def find_by_code(self, join_code: str) -> MatchCoordinator | None:
        match_id = await self._store.find_by_join_code(join_code)
        if match_id is None:
            return None
        return await self.get(match_id)

    async def list_states(self) -> tuple[MatchState, ...]:
        persisted = await self._store.list_states()
        return tuple(
            self._coordinators[state.match_id].state
            if state.match_id in self._coordinators
            else state
            for state in persisted
        )

    async def known_match_ids(self) -> tuple[str, ...]:
        async with self._lock:
            return tuple(sorted(self._coordinators))

    async def discover_active_matches(self) -> tuple[str, ...]:
        """Restore every persisted running match not yet known in this process."""

        for match_id in await self._store.list_active_match_ids():
            try:
                await self.get(match_id)
            except (MatchStoreError, ValueError):
                logger.exception("active match restore failed", extra={"id": match_id})
        return await self.known_match_ids()
