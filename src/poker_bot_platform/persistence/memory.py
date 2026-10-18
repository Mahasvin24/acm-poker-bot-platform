from __future__ import annotations

import asyncio
from dataclasses import dataclass

from poker_bot_platform.domain import (
    ActionRecord,
    DomainEvent,
    HandSnapshot,
    PendingDecision,
    TableStatus,
)
from poker_bot_platform.persistence.repository import (
    CommitResult,
    DecisionConflictError,
    HandStartCommitResult,
    PersistedTableState,
    PersistenceError,
    StatusConflictError,
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
        self._tables: dict[str, _MemoryTable] = {}
        self._actions: dict[tuple[str, str], ActionRecord] = {}
        self._events: list[tuple[str, int, DomainEvent]] = []
        self._audit: list[dict[str, object]] = []
        self._lock = asyncio.Lock()
        self.fail_next: str | None = None

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

    async def update_table_status(
        self,
        table_id: str,
        *,
        expected_version: int,
        expected_status: TableStatus,
        status: TableStatus,
    ) -> TableStatus:
        async with self._lock:
            self._maybe_fail("update_table_status")
            table = self._tables.get(table_id)
            if table is None:
                raise TableNotFoundError(table_id)
            if table.snapshot.table_version != expected_version:
                raise VersionConflictError(
                    f"expected version {expected_version}, found {table.snapshot.table_version}"
                )
            if table.status is status:
                return status
            if table.status is not expected_status:
                raise StatusConflictError(
                    f"expected status {expected_status.value}, found {table.status.value}"
                )
            table.status = status
            return status

    async def quarantine_table(
        self,
        table_id: str,
        *,
        expected_version: int,
        expected_status: TableStatus,
        match_id: str,
        detail: str,
    ) -> TableStatus:
        async with self._lock:
            self._maybe_fail("quarantine_table")
            table = self._tables.get(table_id)
            if table is None:
                raise TableNotFoundError(table_id)
            if table.snapshot.table_version != expected_version:
                raise VersionConflictError(
                    f"expected version {expected_version}, found {table.snapshot.table_version}"
                )
            if table.status is TableStatus.QUARANTINED:
                return TableStatus.QUARANTINED
            if table.status is not expected_status:
                raise StatusConflictError(
                    f"expected status {expected_status.value}, found {table.status.value}"
                )
            table.status = TableStatus.QUARANTINED
            self._audit.append(
                {
                    "actor_id": "system",
                    "command": "quarantine_table",
                    "outcome": "failure",
                    "match_id": match_id,
                    "payload": {
                        "table_id": table_id,
                        "failure_reason": "engine_invariant",
                    },
                    "detail": detail,
                }
            )
            return table.status

    async def commit_next_hand(
        self,
        *,
        expected_version: int,
        snapshot: HandSnapshot,
        events: tuple[DomainEvent, ...],
    ) -> HandStartCommitResult:
        async with self._lock:
            self._maybe_fail("commit_next_hand")
            table = self._tables.get(snapshot.table_id)
            if table is None:
                raise TableNotFoundError(snapshot.table_id)
            if (
                table.snapshot.table_version == snapshot.table_version
                and table.snapshot.hand_id == snapshot.hand_id
            ):
                if table.snapshot != snapshot:
                    raise DecisionConflictError("next hand identity already has different state")
                return HandStartCommitResult(snapshot=table.snapshot, idempotent=True)
            self._validate_next_hand(table, expected_version, snapshot)
            table.snapshot = snapshot
            self._events.extend(
                (snapshot.table_id, snapshot.table_version, event) for event in events
            )
            return HandStartCommitResult(snapshot=snapshot)

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
        match_id: str | None = None,
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
                    "match_id": match_id,
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

    @property
    def audit_entries(self) -> tuple[dict[str, object], ...]:
        return tuple(self._audit)

    @staticmethod
    def _validate_next_hand(
        table: _MemoryTable, expected_version: int, snapshot: HandSnapshot
    ) -> None:
        previous = table.snapshot
        if table.status is not TableStatus.RUNNING:
            raise StatusConflictError("only a running table can start its next hand")
        if table.pending is not None:
            raise DecisionConflictError("cannot start a hand with an unresolved decision")
        if not previous.completed:
            raise DecisionConflictError("current hand is not complete")
        if previous.table_version != expected_version:
            raise VersionConflictError(
                f"expected version {expected_version}, found {previous.table_version}"
            )
        if snapshot.table_version != expected_version + 1:
            raise VersionConflictError("next hand must advance exactly one version")
        if snapshot.match_id != previous.match_id:
            raise DecisionConflictError("next hand changed match identity")
        if snapshot.hand_id == previous.hand_id or snapshot.hand_number != previous.hand_number + 1:
            raise DecisionConflictError("next hand identity or number is invalid")
        if snapshot.action_history:
            raise DecisionConflictError("a new hand cannot contain action history")
