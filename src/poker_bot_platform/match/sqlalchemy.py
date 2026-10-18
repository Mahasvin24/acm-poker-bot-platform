from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from poker_bot_platform.match.models import (
    ACTIVE_MATCH_STATUSES,
    OPEN_MATCH_STATUSES,
    AuditEntry,
    MatchState,
)
from poker_bot_platform.match.store import (
    JoinCodeConflict,
    MatchNotFoundError,
    MatchStoreError,
    MatchVersionConflict,
)
from poker_bot_platform.persistence.models import AuditLogRow, MatchRow


class SqlAlchemyMatchStore:
    """Stores match state and its audit entry in the same transaction."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, state: MatchState, audit: AuditEntry) -> None:
        try:
            async with self._sessions() as session, session.begin():
                session.add(
                    MatchRow(
                        id=state.match_id,
                        status=state.status.value,
                        join_code=state.join_code,
                        state=state.model_dump(mode="json"),
                        version=state.revision,
                    )
                )
                await session.flush()
                self._append_audit(session, state.match_id, audit)
        except IntegrityError as exc:
            raise JoinCodeConflict("match identifier or join code is already in use") from exc
        except SQLAlchemyError as exc:
            raise MatchStoreError("match database operation failed") from exc

    async def save(
        self,
        state: MatchState,
        *,
        expected_revision: int,
        audit: AuditEntry,
    ) -> None:
        try:
            async with self._sessions() as session, session.begin():
                row = await session.scalar(
                    select(MatchRow).where(MatchRow.id == state.match_id).with_for_update()
                )
                if row is None:
                    raise MatchNotFoundError("match does not exist")
                if row.version != expected_revision:
                    raise MatchVersionConflict(
                        f"expected revision {expected_revision}, found {row.version}"
                    )
                if state.revision != expected_revision + 1:
                    raise MatchVersionConflict("saved state must advance one revision")
                row.state = state.model_dump(mode="json")
                row.status = state.status.value
                row.join_code = state.join_code
                row.version = state.revision
                self._append_audit(session, state.match_id, audit)
        except MatchStoreError:
            raise
        except IntegrityError as exc:
            raise JoinCodeConflict("join code is already in use") from exc
        except SQLAlchemyError as exc:
            raise MatchStoreError("match database operation failed") from exc

    async def load(self, match_id: str) -> MatchState:
        try:
            async with self._sessions() as session:
                row = await session.get(MatchRow, match_id)
                if row is None:
                    raise MatchNotFoundError("match does not exist")
                state = MatchState.model_validate(row.state)
                if row.version != state.revision or row.status != state.status.value:
                    raise MatchVersionConflict("match row and state disagree")
                return state
        except MatchStoreError:
            raise
        except SQLAlchemyError as exc:
            raise MatchStoreError("match database operation failed") from exc

    async def find_by_join_code(self, join_code: str) -> str | None:
        try:
            async with self._sessions() as session:
                return await session.scalar(
                    select(MatchRow.id).where(
                        MatchRow.join_code == join_code,
                        MatchRow.status.in_([status.value for status in OPEN_MATCH_STATUSES]),
                    )
                )
        except SQLAlchemyError as exc:
            raise MatchStoreError("match database operation failed") from exc

    async def list_states(self) -> tuple[MatchState, ...]:
        try:
            async with self._sessions() as session:
                rows = await session.scalars(select(MatchRow).order_by(MatchRow.created_at))
                return tuple(MatchState.model_validate(row.state) for row in rows)
        except SQLAlchemyError as exc:
            raise MatchStoreError("match database operation failed") from exc

    async def list_active_match_ids(self) -> tuple[str, ...]:
        try:
            async with self._sessions() as session:
                rows = await session.scalars(
                    select(MatchRow.id)
                    .where(MatchRow.status.in_([status.value for status in ACTIVE_MATCH_STATUSES]))
                    .order_by(MatchRow.id)
                )
                return tuple(rows)
        except SQLAlchemyError as exc:
            raise MatchStoreError("match database operation failed") from exc

    @staticmethod
    def _append_audit(session: AsyncSession, match_id: str, audit: AuditEntry) -> None:
        session.add(
            AuditLogRow(
                match_id=match_id,
                actor_id=audit.actor_id,
                command=audit.command,
                outcome=audit.outcome,
                detail=audit.detail,
                payload={},
            )
        )
