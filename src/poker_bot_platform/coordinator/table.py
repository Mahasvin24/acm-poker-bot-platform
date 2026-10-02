from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from poker_bot_platform.domain import (
    ActionRecord,
    ActionType,
    EngineTransition,
    FailureReason,
    HandSnapshot,
    PendingDecision,
    PlayerAction,
    StartHandRequest,
)
from poker_bot_platform.engine import PokerEngine
from poker_bot_platform.persistence import PersistenceError, TableRepository

Actor = Callable[[PendingDecision, HandSnapshot], Awaitable[PlayerAction]]
Clock = Callable[[], datetime]


class CoordinatorError(RuntimeError):
    pass


class CoordinatorNotReadyError(CoordinatorError):
    pass


class InvalidActionError(CoordinatorError):
    pass


class ActorDecisionFailure(CoordinatorError):
    def __init__(self, reason: FailureReason, detail: str | None = None) -> None:
        super().__init__(detail or reason.value)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class CoordinatorState:
    snapshot: HandSnapshot | None
    pending: PendingDecision | None
    database_paused: bool


class TableCoordinator:
    """Serializes all commands for one table and advances state only after commit."""

    def __init__(
        self,
        table_id: str,
        engine: PokerEngine,
        repository: TableRepository,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.table_id = table_id
        self._engine = engine
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._snapshot: HandSnapshot | None = None
        self._pending: PendingDecision | None = None
        self._database_paused = False
        self._command_lock = asyncio.Lock()

    @property
    def state(self) -> CoordinatorState:
        return CoordinatorState(
            snapshot=self._snapshot,
            pending=self._pending,
            database_paused=self._database_paused,
        )

    async def start_table(self, request: StartHandRequest) -> HandSnapshot:
        async with self._command_lock:
            if self._snapshot is not None:
                raise CoordinatorError("table is already initialized")
            if request.table_id != self.table_id:
                raise CoordinatorError("request targets a different table")
            transition = self._engine.start_hand(request)
            self._validate_started_transition(request, transition)
            try:
                await self._repository.create_table(transition.snapshot, transition.events)
            except PersistenceError:
                self._database_paused = True
                raise
            self._snapshot = transition.snapshot
            self._pending = None
            self._database_paused = False
            return transition.snapshot

    async def restore(self) -> HandSnapshot:
        """Restore durable state and deterministically resolve any interrupted decision."""

        async with self._command_lock:
            try:
                stored = await self._repository.load_table(self.table_id)
            except PersistenceError:
                self._database_paused = True
                raise

            snapshot = self._engine.restore(stored.snapshot)
            self._snapshot = snapshot
            self._pending = stored.pending
            self._database_paused = False
            if stored.pending is not None:
                try:
                    await self._apply_locked(
                        self._fallback_action(stored.pending),
                        automatic=True,
                        failure_reason=FailureReason.RESTART_RECOVERY,
                    )
                except PersistenceError:
                    # _apply_locked preserves the restored, pre-action snapshot on failure.
                    raise
            assert self._snapshot is not None
            return self._snapshot

    async def open_decision(self, deadline_at: datetime) -> PendingDecision:
        async with self._command_lock:
            return await self._open_decision_locked(deadline_at)

    async def submit_action(self, action: PlayerAction) -> HandSnapshot:
        async with self._command_lock:
            self._require_available()
            self._validate_action_identity(action)
            self._validate_legal_action(action)
            if self._now() >= self._require_pending().deadline_at:
                raise InvalidActionError("decision deadline has passed")
            return await self._apply_locked(action)

    async def expire_decision(self) -> HandSnapshot:
        """Apply the deterministic timeout action after a human or bot deadline."""

        async with self._command_lock:
            self._require_available()
            pending = self._require_pending()
            if self._now() < pending.deadline_at:
                raise CoordinatorNotReadyError("decision deadline has not passed")
            return await self._apply_locked(
                self._fallback_action(pending),
                automatic=True,
                failure_reason=FailureReason.TIMEOUT,
            )

    async def request_actor_action(self, actor: Actor, deadline_at: datetime) -> HandSnapshot:
        """Persist intent, wait without a DB transaction, then atomically commit one result."""

        async with self._command_lock:
            pending = await self._open_decision_locked(deadline_at)
            snapshot = self._require_snapshot()
            timeout_seconds = max(0.0, (pending.deadline_at - self._now()).total_seconds())
            try:
                action = await asyncio.wait_for(
                    actor(pending, snapshot),
                    timeout=timeout_seconds,
                )
                if self._now() >= pending.deadline_at:
                    raise ActorDecisionFailure(FailureReason.TIMEOUT)
                self._validate_action_identity(action)
                self._validate_legal_action(action)
            except TimeoutError:
                return await self._apply_locked(
                    self._fallback_action(pending),
                    automatic=True,
                    failure_reason=FailureReason.TIMEOUT,
                )
            except ActorDecisionFailure as exc:
                return await self._apply_locked(
                    self._fallback_action(pending),
                    automatic=True,
                    failure_reason=exc.reason,
                )
            except InvalidActionError as exc:
                reason = (
                    FailureReason.STALE
                    if "decision" in str(exc) or "version" in str(exc)
                    else FailureReason.ILLEGAL_ACTION
                )
                return await self._apply_locked(
                    self._fallback_action(pending),
                    automatic=True,
                    failure_reason=reason,
                )
            except Exception:
                return await self._apply_locked(
                    self._fallback_action(pending),
                    automatic=True,
                    failure_reason=FailureReason.CONNECTION,
                )
            try:
                return await self._apply_locked(action)
            except InvalidActionError:
                return await self._apply_locked(
                    self._fallback_action(pending),
                    automatic=True,
                    failure_reason=FailureReason.ILLEGAL_ACTION,
                )

    async def _open_decision_locked(self, deadline_at: datetime) -> PendingDecision:
        self._require_available()
        snapshot = self._require_snapshot()
        if self._pending is not None:
            return self._pending
        if snapshot.completed or snapshot.acting_seat is None or not snapshot.legal_actions:
            raise CoordinatorNotReadyError("table is not waiting for an action")
        if deadline_at.tzinfo is None or deadline_at.utcoffset() is None:
            raise ValueError("deadline must be timezone-aware")
        pending = PendingDecision(
            decision_id=str(uuid.uuid4()),
            table_id=snapshot.table_id,
            hand_id=snapshot.hand_id,
            table_version=snapshot.table_version,
            seat=snapshot.acting_seat,
            deadline_at=deadline_at,
            legal_actions=snapshot.legal_actions,
        )
        try:
            pending = await self._repository.create_pending(pending)
        except PersistenceError:
            self._database_paused = True
            raise
        self._pending = pending
        return pending

    async def _apply_locked(
        self,
        action: PlayerAction,
        *,
        automatic: bool = False,
        failure_reason: FailureReason | None = None,
    ) -> HandSnapshot:
        snapshot = self._require_snapshot()
        self._validate_action_identity(action)
        self._validate_legal_action(action)
        try:
            transition = self._engine.apply_action(snapshot, action)
        except ValueError as exc:
            raise InvalidActionError(str(exc)) from exc
        transition, record = self._prepare_transition(
            snapshot,
            action,
            transition,
            automatic=automatic,
            failure_reason=failure_reason,
        )
        try:
            result = await self._repository.commit_transition(
                expected_version=snapshot.table_version,
                snapshot=transition.snapshot,
                action=record,
                events=transition.events,
            )
        except PersistenceError:
            self._database_paused = True
            raise
        self._snapshot = result.snapshot
        self._pending = None
        self._database_paused = False
        return result.snapshot

    def _prepare_transition(
        self,
        previous: HandSnapshot,
        action: PlayerAction,
        transition: EngineTransition,
        *,
        automatic: bool,
        failure_reason: FailureReason | None,
    ) -> tuple[EngineTransition, ActionRecord]:
        updated = transition.snapshot
        if updated.table_id != previous.table_id or updated.hand_id != previous.hand_id:
            raise CoordinatorError("engine transition changed table or hand identity")
        if updated.table_version != previous.table_version + 1:
            raise CoordinatorError("engine transition must advance exactly one table version")
        if len(updated.action_history) != len(previous.action_history) + 1:
            raise CoordinatorError("engine transition must append exactly one action")
        record = updated.action_history[-1]
        if record.decision_id != action.decision_id or record.seat != action.seat:
            raise CoordinatorError("engine appended an action with the wrong identity")
        record = record.model_copy(
            update={"automatic": automatic, "failure_reason": failure_reason}
        )
        updated = updated.model_copy(
            update={"action_history": (*updated.action_history[:-1], record)}
        )
        return transition.model_copy(update={"snapshot": updated}), record

    def _validate_started_transition(
        self, request: StartHandRequest, transition: EngineTransition
    ) -> None:
        snapshot = transition.snapshot
        if snapshot.table_id != request.table_id or snapshot.tournament_id != request.tournament_id:
            raise CoordinatorError("engine returned the wrong table identity")
        if snapshot.table_version != request.table_version:
            raise CoordinatorError("starting a hand must not advance table version")

    def _validate_action_identity(self, action: PlayerAction) -> None:
        pending = self._require_pending()
        if action.decision_id != pending.decision_id:
            raise InvalidActionError("decision identifier is stale")
        if action.table_version != pending.table_version:
            raise InvalidActionError("table version is stale")
        if action.seat != pending.seat:
            raise InvalidActionError("action is from the wrong seat")

    def _validate_legal_action(self, action: PlayerAction) -> None:
        pending = self._require_pending()
        legal = next(
            (candidate for candidate in pending.legal_actions if candidate.action is action.action),
            None,
        )
        if legal is None:
            raise InvalidActionError("action is not legal")
        if action.action is ActionType.RAISE:
            assert action.amount_to is not None
            assert legal.min_amount_to is not None and legal.max_amount_to is not None
            if not legal.min_amount_to <= action.amount_to <= legal.max_amount_to:
                raise InvalidActionError("raise amount is outside legal bounds")

    def _fallback_action(self, pending: PendingDecision) -> PlayerAction:
        legal_types = {item.action for item in pending.legal_actions}
        action_type = ActionType.CHECK if ActionType.CHECK in legal_types else ActionType.FOLD
        if action_type not in legal_types:
            raise CoordinatorError("pending decision permits neither check nor fold fallback")
        return PlayerAction(
            decision_id=pending.decision_id,
            table_version=pending.table_version,
            seat=pending.seat,
            action=action_type,
        )

    def _require_available(self) -> None:
        if self._database_paused:
            raise CoordinatorNotReadyError("table is paused after a database failure; restore it")

    def _require_snapshot(self) -> HandSnapshot:
        if self._snapshot is None:
            raise CoordinatorNotReadyError("table has not been initialized or restored")
        return self._snapshot

    def _require_pending(self) -> PendingDecision:
        if self._pending is None:
            raise CoordinatorNotReadyError("table has no pending decision")
        return self._pending

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("coordinator clock must return a timezone-aware datetime")
        return value
