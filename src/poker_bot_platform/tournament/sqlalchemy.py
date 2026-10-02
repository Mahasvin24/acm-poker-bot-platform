from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from poker_bot_platform.persistence.models import AuditLogRow, TournamentRow
from poker_bot_platform.tournament.models import AuditEntry, TournamentState
from poker_bot_platform.tournament.store import (
    TournamentStoreError,
    TournamentVersionConflict,
)

_STATE_KEY = "tournament_state"


class SqlAlchemyTournamentStore:
    """Stores tournament state and its audit entry in the same transaction."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, state: TournamentState, audit: AuditEntry) -> None:
        try:
            async with self._sessions() as session, session.begin():
                row = await self._locked_row(session, state.tournament_id)
                existing = row.config.get(_STATE_KEY)
                if existing is not None:
                    materialized = TournamentState.model_validate(existing)
                    if materialized == state:
                        return
                    raise TournamentStoreError("tournament state already exists")
                if row.version != 0:
                    raise TournamentVersionConflict("new tournament row is not at version zero")
                row.config = {_STATE_KEY: state.model_dump(mode="json")}
                row.status = state.status.value
                self._append_audit(session, state.tournament_id, audit)
        except TournamentStoreError:
            raise
        except SQLAlchemyError as exc:
            raise TournamentStoreError("tournament database operation failed") from exc

    async def save(
        self,
        state: TournamentState,
        *,
        expected_revision: int,
        audit: AuditEntry,
    ) -> None:
        try:
            async with self._sessions() as session, session.begin():
                row = await self._locked_row(session, state.tournament_id)
                current_raw = row.config.get(_STATE_KEY)
                if current_raw is None:
                    raise TournamentStoreError("tournament state is not initialized")
                current = TournamentState.model_validate(current_raw)
                if current.revision != expected_revision or row.version != expected_revision:
                    raise TournamentVersionConflict(
                        f"expected revision {expected_revision}, found {current.revision}"
                    )
                if state.revision != expected_revision + 1:
                    raise TournamentVersionConflict("saved state must advance one revision")
                row.config = {_STATE_KEY: state.model_dump(mode="json")}
                row.status = state.status.value
                row.version = state.revision
                self._append_audit(session, state.tournament_id, audit)
        except TournamentStoreError:
            raise
        except SQLAlchemyError as exc:
            raise TournamentStoreError("tournament database operation failed") from exc

    async def load(self, tournament_id: str) -> TournamentState:
        try:
            async with self._sessions() as session:
                row = await session.get(TournamentRow, tournament_id)
                if row is None:
                    raise TournamentStoreError("tournament does not exist")
                raw = row.config.get(_STATE_KEY)
                if raw is None:
                    raise TournamentStoreError("tournament state is not initialized")
                state = TournamentState.model_validate(raw)
                if row.version != state.revision or row.status != state.status.value:
                    raise TournamentVersionConflict("tournament row and state disagree")
                return state
        except TournamentStoreError:
            raise
        except SQLAlchemyError as exc:
            raise TournamentStoreError("tournament database operation failed") from exc

    @staticmethod
    async def _locked_row(session: AsyncSession, tournament_id: str) -> TournamentRow:
        row = await session.scalar(
            select(TournamentRow).where(TournamentRow.id == tournament_id).with_for_update()
        )
        if row is None:
            raise TournamentStoreError("tournament does not exist")
        return row

    @staticmethod
    def _append_audit(
        session: AsyncSession,
        tournament_id: str,
        audit: AuditEntry,
    ) -> None:
        session.add(
            AuditLogRow(
                tournament_id=tournament_id,
                actor_id=audit.actor_id,
                command=audit.command,
                outcome=audit.outcome,
                detail=audit.detail,
                payload={},
            )
        )
