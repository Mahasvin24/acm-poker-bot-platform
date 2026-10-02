from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from poker_bot_platform.domain import (
    ActionRecord,
    DomainEvent,
    HandSnapshot,
    PendingDecision,
    TableStatus,
    TournamentStatus,
)
from poker_bot_platform.persistence.models import (
    ActionRow,
    AuditLogRow,
    DomainEventRow,
    PendingDecisionRow,
    TableRow,
    TableSnapshotRow,
    TournamentRow,
)
from poker_bot_platform.persistence.repository import (
    CommitResult,
    DecisionConflictError,
    PersistedTableState,
    PersistenceError,
    TableNotFoundError,
    VersionConflictError,
    utc_now,
)


class SqlAlchemyTableRepository:
    """PostgreSQL repository. Every public write is one short transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self._sessions() as session, session.begin():
                yield session
        except PersistenceError:
            raise
        except SQLAlchemyError as exc:
            raise PersistenceError("database operation failed") from exc

    async def create_tournament(
        self,
        tournament_id: str,
        config: dict[str, object],
        *,
        status: TournamentStatus = TournamentStatus.DRAFT,
    ) -> None:
        try:
            async with self._transaction() as session:
                session.add(
                    TournamentRow(id=tournament_id, status=status.value, config=dict(config))
                )
        except PersistenceError as exc:
            if isinstance(exc.__cause__, IntegrityError):
                raise DecisionConflictError(f"tournament {tournament_id!r} already exists") from exc
            raise

    async def create_table(
        self,
        snapshot: HandSnapshot,
        events: tuple[DomainEvent, ...] = (),
        *,
        status: TableStatus = TableStatus.RUNNING,
    ) -> PersistedTableState:
        try:
            async with self._transaction() as session:
                session.add(
                    TableRow(
                        id=snapshot.table_id,
                        tournament_id=snapshot.tournament_id,
                        status=status.value,
                        version=snapshot.table_version,
                        current_hand_id=snapshot.hand_id,
                    )
                )
                session.add(
                    TableSnapshotRow(
                        table_id=snapshot.table_id,
                        version=snapshot.table_version,
                        snapshot=snapshot.model_dump(mode="json"),
                    )
                )
                self._add_events(session, snapshot, events)
        except PersistenceError as exc:
            if isinstance(exc.__cause__, IntegrityError):
                raise DecisionConflictError(f"table {snapshot.table_id!r} already exists") from exc
            raise
        return PersistedTableState(snapshot=snapshot, status=status)

    async def load_table(self, table_id: str) -> PersistedTableState:
        async with self._transaction() as session:
            row = await session.scalar(
                select(TableRow).where(TableRow.id == table_id).with_for_update()
            )
            if row is None:
                raise TableNotFoundError(table_id)
            snapshot_row = await session.get(TableSnapshotRow, table_id)
            if snapshot_row is None:
                raise PersistenceError("table is missing its recovery snapshot")
            if row.version != snapshot_row.version:
                raise PersistenceError("table and recovery snapshot versions differ")
            pending_row = await session.scalar(
                select(PendingDecisionRow).where(
                    PendingDecisionRow.table_id == table_id,
                    PendingDecisionRow.status == "pending",
                )
            )
            return PersistedTableState(
                snapshot=HandSnapshot.model_validate(snapshot_row.snapshot),
                status=TableStatus(row.status),
                pending=self._pending_from_row(pending_row) if pending_row else None,
            )

    async def create_pending(self, decision: PendingDecision) -> PendingDecision:
        try:
            async with self._transaction() as session:
                table = await session.scalar(
                    select(TableRow).where(TableRow.id == decision.table_id).with_for_update()
                )
                if table is None:
                    raise TableNotFoundError(decision.table_id)
                if table.version != decision.table_version:
                    raise VersionConflictError(
                        f"expected version {decision.table_version}, found {table.version}"
                    )
                existing = await session.scalar(
                    select(PendingDecisionRow).where(
                        PendingDecisionRow.table_id == decision.table_id,
                        PendingDecisionRow.status == "pending",
                    )
                )
                if existing is not None:
                    materialized = self._pending_from_row(existing)
                    if materialized == decision:
                        return materialized
                    raise DecisionConflictError("table already has an unresolved decision")
                session.add(
                    PendingDecisionRow(
                        decision_id=decision.decision_id,
                        table_id=decision.table_id,
                        hand_id=decision.hand_id,
                        table_version=decision.table_version,
                        seat=decision.seat,
                        deadline_at=decision.deadline_at,
                        legal_actions=[
                            item.model_dump(mode="json") for item in decision.legal_actions
                        ],
                        status="pending",
                    )
                )
        except PersistenceError as exc:
            if isinstance(exc.__cause__, IntegrityError):
                raise DecisionConflictError(
                    "pending decision conflicts with existing state"
                ) from exc
            raise
        return decision

    async def commit_transition(
        self,
        *,
        expected_version: int,
        snapshot: HandSnapshot,
        action: ActionRecord,
        events: tuple[DomainEvent, ...],
    ) -> CommitResult:
        async with self._transaction() as session:
            table = await session.scalar(
                select(TableRow).where(TableRow.id == snapshot.table_id).with_for_update()
            )
            if table is None:
                raise TableNotFoundError(snapshot.table_id)

            existing = await session.scalar(
                select(ActionRow).where(
                    ActionRow.table_id == snapshot.table_id,
                    ActionRow.decision_id == action.decision_id,
                )
            )
            if existing is not None:
                stored = await session.get(TableSnapshotRow, snapshot.table_id)
                if stored is None:
                    raise PersistenceError("table is missing its recovery snapshot")
                return CommitResult(
                    snapshot=HandSnapshot.model_validate(stored.snapshot),
                    action=self._action_from_row(existing),
                    idempotent=True,
                )

            if table.version != expected_version:
                raise VersionConflictError(
                    f"expected version {expected_version}, found {table.version}"
                )
            if snapshot.table_version != expected_version + 1:
                raise VersionConflictError("committed snapshot must advance exactly one version")

            pending = await session.scalar(
                select(PendingDecisionRow)
                .where(
                    PendingDecisionRow.decision_id == action.decision_id,
                    PendingDecisionRow.table_id == snapshot.table_id,
                    PendingDecisionRow.status == "pending",
                )
                .with_for_update()
            )
            if pending is None:
                raise DecisionConflictError("action does not resolve the pending decision")
            if pending.table_version != expected_version:
                raise DecisionConflictError("pending decision version does not match")
            if pending.hand_id != snapshot.hand_id:
                raise DecisionConflictError("pending decision hand does not match")
            if pending.seat != action.seat:
                raise DecisionConflictError("pending decision seat does not match action")
            if not snapshot.action_history or snapshot.action_history[-1] != action:
                raise DecisionConflictError("snapshot does not contain the committed action")

            action_row = ActionRow(
                tournament_id=snapshot.tournament_id,
                table_id=snapshot.table_id,
                hand_id=snapshot.hand_id,
                table_version=snapshot.table_version,
                sequence=action.sequence,
                decision_id=action.decision_id,
                seat=action.seat,
                action=action.action.value,
                amount_to=action.amount_to,
                automatic=action.automatic,
                failure_reason=action.failure_reason.value if action.failure_reason else None,
                created_at=action.created_at,
            )
            session.add(action_row)
            await session.flush()

            stored = await session.get(TableSnapshotRow, snapshot.table_id)
            if stored is None:
                raise PersistenceError("table is missing its recovery snapshot")
            stored.version = snapshot.table_version
            stored.snapshot = snapshot.model_dump(mode="json")
            table.version = snapshot.table_version
            table.current_hand_id = snapshot.hand_id
            pending.status = "resolved"
            pending.resolved_action_id = action_row.id
            pending.resolved_at = utc_now()
            self._add_events(session, snapshot, events)
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
        async with self._transaction() as session:
            session.add(
                AuditLogRow(
                    tournament_id=tournament_id,
                    actor_id=actor_id,
                    command=command,
                    payload=payload or {},
                    outcome=outcome,
                    detail=detail,
                )
            )

    @staticmethod
    def _pending_from_row(row: PendingDecisionRow) -> PendingDecision:
        return PendingDecision.model_validate(
            {
                "decision_id": row.decision_id,
                "table_id": row.table_id,
                "hand_id": row.hand_id,
                "table_version": row.table_version,
                "seat": row.seat,
                "deadline_at": row.deadline_at,
                "legal_actions": row.legal_actions,
            }
        )

    @staticmethod
    def _action_from_row(row: ActionRow) -> ActionRecord:
        return ActionRecord.model_validate(
            {
                "sequence": row.sequence,
                "decision_id": row.decision_id,
                "seat": row.seat,
                "action": row.action,
                "amount_to": row.amount_to,
                "automatic": row.automatic,
                "failure_reason": row.failure_reason,
                "created_at": row.created_at,
            }
        )

    @staticmethod
    def _add_events(
        session: AsyncSession,
        snapshot: HandSnapshot,
        events: tuple[DomainEvent, ...],
    ) -> None:
        for ordinal, event in enumerate(events, start=1):
            session.add(
                DomainEventRow(
                    tournament_id=snapshot.tournament_id,
                    table_id=snapshot.table_id,
                    hand_id=snapshot.hand_id,
                    table_version=snapshot.table_version,
                    ordinal=ordinal,
                    event_type=event.event_type,
                    payload=event.payload,
                )
            )
