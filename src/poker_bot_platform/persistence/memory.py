from __future__ import annotations

import asyncio
from dataclasses import dataclass

from poker_bot_platform.domain import (
    ActionRecord,
    DomainEvent,
    HandSnapshot,
    PendingDecision,
    TableStatus,
    TournamentStatus,
)
from poker_bot_platform.persistence.repository import (
    CommitResult,
    DecisionConflictError,
    PersistedTableState,
    PersistenceError,
    TableNotFoundError,
    VersionConflictError,
)


@dataclass(slots=True)
class _MemoryTable:
    snapshot: HandSnapshot
    status: TableStatus
    pending: PendingDecision | None = None


class InMemoryTableRepository:
    """Atomic repository double used by coordinator and crash-point tests."""

    def __init__(self) -> None:
        self._tournaments: dict[str, tuple[TournamentStatus, dict[str, object]]] = {}
        self._tables: dict[str, _MemoryTable] = {}
        self._actions: dict[tuple[str, str], ActionRecord] = {}
        self._events: list[tuple[str, int, DomainEvent]] = []
        self._audit: list[dict[str, object]] = []
        self._lock = asyncio.Lock()
        self.fail_next: str | None = None

    async def create_tournament(
        self,
        tournament_id: str,
        config: dict[str, object],
        *,
        status: TournamentStatus = TournamentStatus.DRAFT,
    ) -> None:
        async with self._lock:
            self._maybe_fail("create_tournament")
            if tournament_id in self._tournaments:
                raise DecisionConflictError(f"tournament {tournament_id!r} already exists")
            self._tournaments[tournament_id] = (status, config.copy())

    def inject_failure(self, operation: str) -> None:
        self.fail_next = operation

    def _maybe_fail(self, operation: str) -> None:
        if self.fail_next == operation:
            self.fail_next = None
            raise PersistenceError(f"injected {operation} failure")

    async def create_table(
        self,
        snapshot: HandSnapshot,
        events: tuple[DomainEvent, ...] = (),
        *,
        status: TableStatus = TableStatus.RUNNING,
    ) -> PersistedTableState:
        async with self._lock:
            self._maybe_fail("create_table")
            if snapshot.tournament_id not in self._tournaments:
                raise TableNotFoundError(f"tournament {snapshot.tournament_id!r}")
            if snapshot.table_id in self._tables:
                raise DecisionConflictError(f"table {snapshot.table_id!r} already exists")
            self._tables[snapshot.table_id] = _MemoryTable(snapshot=snapshot, status=status)
            self._events.extend(
                (snapshot.table_id, snapshot.table_version, event) for event in events
            )
            return PersistedTableState(snapshot=snapshot, status=status)

    async def load_table(self, table_id: str) -> PersistedTableState:
        async with self._lock:
            self._maybe_fail("load_table")
            table = self._tables.get(table_id)
            if table is None:
                raise TableNotFoundError(table_id)
            return PersistedTableState(
                snapshot=table.snapshot,
                status=table.status,
                pending=table.pending,
            )

    async def create_pending(self, decision: PendingDecision) -> PendingDecision:
        async with self._lock:
            self._maybe_fail("create_pending")
            table = self._tables.get(decision.table_id)
            if table is None:
                raise TableNotFoundError(decision.table_id)
            if table.snapshot.table_version != decision.table_version:
                raise VersionConflictError(
                    "expected version "
                    f"{decision.table_version}, found {table.snapshot.table_version}"
                )
            if table.pending is not None:
                if table.pending == decision:
                    return table.pending
                raise DecisionConflictError("table already has an unresolved decision")
            table.pending = decision
            return decision

    async def commit_transition(
        self,
        *,
        expected_version: int,
        snapshot: HandSnapshot,
        action: ActionRecord,
        events: tuple[DomainEvent, ...],
    ) -> CommitResult:
        async with self._lock:
            self._maybe_fail("commit_transition")
            table = self._tables.get(snapshot.table_id)
            if table is None:
                raise TableNotFoundError(snapshot.table_id)

            action_key = (snapshot.table_id, action.decision_id)
            existing = self._actions.get(action_key)
            if existing is not None:
                return CommitResult(snapshot=table.snapshot, action=existing, idempotent=True)

            if table.snapshot.table_version != expected_version:
                raise VersionConflictError(
                    f"expected version {expected_version}, found {table.snapshot.table_version}"
                )
            if snapshot.table_version != expected_version + 1:
                raise VersionConflictError("committed snapshot must advance exactly one version")
            if table.pending is None or table.pending.decision_id != action.decision_id:
                raise DecisionConflictError("action does not resolve the pending decision")
            if table.pending.table_version != expected_version:
                raise DecisionConflictError("pending decision version does not match")
            if table.pending.hand_id != snapshot.hand_id:
                raise DecisionConflictError("pending decision hand does not match")
            if table.pending.seat != action.seat:
                raise DecisionConflictError("pending decision seat does not match action")
            if not snapshot.action_history or snapshot.action_history[-1] != action:
                raise DecisionConflictError("snapshot does not contain the committed action")

            # All validation occurs before these mutations, mirroring one database transaction.
            self._actions[action_key] = action
            self._events.extend(
                (snapshot.table_id, snapshot.table_version, event) for event in events
            )
            table.snapshot = snapshot
            table.pending = None
            return CommitResult(snapshot=snapshot, action=action)

    async def append_audit(
        self,
        *,
        actor_id: str,
        command: str,
        outcome: str,
        tournament_id: str | None = None,
        payload: dict[str, object] | None = None,
        detail: str | None = None,
    ) -> None:
        async with self._lock:
            self._maybe_fail("append_audit")
            self._audit.append(
                {
                    "actor_id": actor_id,
                    "command": command,
                    "outcome": outcome,
                    "tournament_id": tournament_id,
                    "payload": payload or {},
                    "detail": detail,
                }
            )

    @property
    def actions(self) -> tuple[ActionRecord, ...]:
        return tuple(self._actions.values())

    @property
    def events(self) -> tuple[tuple[str, int, DomainEvent], ...]:
        return tuple(self._events)
