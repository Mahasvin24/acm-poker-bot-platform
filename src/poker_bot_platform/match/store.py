from __future__ import annotations

import asyncio
from typing import Protocol

from poker_bot_platform.match.models import (
    ACTIVE_MATCH_STATUSES,
    OPEN_MATCH_STATUSES,
    AuditEntry,
    MatchState,
)


class MatchStoreError(RuntimeError):
    pass


class MatchNotFoundError(MatchStoreError):
    pass


class MatchVersionConflict(MatchStoreError):
    pass


class JoinCodeConflict(MatchStoreError):
    pass


class MatchStore(Protocol):
    async def create(self, state: MatchState, audit: AuditEntry) -> None: ...

    async def save(
        self,
        state: MatchState,
        *,
        expected_revision: int,
        audit: AuditEntry,
    ) -> None: ...

    async def load(self, match_id: str) -> MatchState: ...

    async def find_by_join_code(self, join_code: str) -> str | None: ...

    async def list_states(self) -> tuple[MatchState, ...]: ...

    async def list_active_match_ids(self) -> tuple[str, ...]: ...


class InMemoryMatchStore:
    """Atomic match-state store for tests and local simulations."""

    def __init__(self) -> None:
        self._states: dict[str, MatchState] = {}
        self._audit: dict[str, list[AuditEntry]] = {}
        self._lock = asyncio.Lock()
        self.fail_next_save = False

    async def create(self, state: MatchState, audit: AuditEntry) -> None:
        async with self._lock:
            if state.match_id in self._states:
                raise MatchStoreError("match already exists")
            self._require_unique_code(state)
            self._states[state.match_id] = state
            self._audit[state.match_id] = [audit]

    async def save(
        self,
        state: MatchState,
        *,
        expected_revision: int,
        audit: AuditEntry,
    ) -> None:
        async with self._lock:
            if self.fail_next_save:
                self.fail_next_save = False
                raise MatchStoreError("injected match save failure")
            current = self._states.get(state.match_id)
            if current is None:
                raise MatchNotFoundError("match does not exist")
            if current.revision != expected_revision:
                raise MatchVersionConflict(
                    f"expected revision {expected_revision}, found {current.revision}"
                )
            if state.revision != expected_revision + 1:
                raise MatchVersionConflict("saved state must advance exactly one revision")
            self._require_unique_code(state)
            self._states[state.match_id] = state
            self._audit[state.match_id].append(audit)

    async def load(self, match_id: str) -> MatchState:
        async with self._lock:
            try:
                return self._states[match_id]
            except KeyError as exc:
                raise MatchNotFoundError("match does not exist") from exc

    async def find_by_join_code(self, join_code: str) -> str | None:
        async with self._lock:
            return next(
                (
                    state.match_id
                    for state in self._states.values()
                    if state.join_code == join_code and state.status in OPEN_MATCH_STATUSES
                ),
                None,
            )

    async def list_states(self) -> tuple[MatchState, ...]:
        async with self._lock:
            return tuple(sorted(self._states.values(), key=lambda item: item.created_at))

    async def list_active_match_ids(self) -> tuple[str, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    match_id
                    for match_id, state in self._states.items()
                    if state.status in ACTIVE_MATCH_STATUSES
                )
            )

    def audit_entries(self, match_id: str) -> tuple[AuditEntry, ...]:
        return tuple(self._audit.get(match_id, ()))

    def _require_unique_code(self, state: MatchState) -> None:
        if state.join_code is None:
            return
        if any(
            other.join_code == state.join_code and other.match_id != state.match_id
            for other in self._states.values()
        ):
            raise JoinCodeConflict("join code is already in use")
