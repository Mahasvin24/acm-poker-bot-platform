from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from poker_bot_platform.auth.db_models import AccountRow, EntrantRow, SessionRow
from poker_bot_platform.auth.models import Account, Entrant, SessionRecord
from poker_bot_platform.auth.repository import (
    AuthConflictError,
    AuthNotFoundError,
    AuthRepositoryError,
)
from poker_bot_platform.domain import EntryKind, Role


class SqlAlchemyAuthRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self._sessions() as session, session.begin():
                yield session
        except AuthRepositoryError:
            raise
        except IntegrityError as exc:
            raise AuthConflictError("account or entrant constraint was violated") from exc
        except SQLAlchemyError as exc:
            raise AuthRepositoryError("account database operation failed") from exc

    async def create_account(self, email: str, password_hash: str, role: Role) -> Account:
        async with self._transaction() as session:
            row = AccountRow(email=email, password_hash=password_hash, role=role.value)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return self._account(row)

    async def get_account_by_email(self, email: str) -> Account | None:
        try:
            async with self._sessions() as session:
                row = await session.scalar(select(AccountRow).where(AccountRow.email == email))
                return self._account(row) if row else None
        except SQLAlchemyError as exc:
            raise AuthRepositoryError("account database operation failed") from exc

    async def get_account(self, account_id: str) -> Account | None:
        try:
            identifier = uuid.UUID(account_id)
        except ValueError:
            return None
        try:
            async with self._sessions() as session:
                row = await session.get(AccountRow, identifier)
                return self._account(row) if row else None
        except SQLAlchemyError as exc:
            raise AuthRepositoryError("account database operation failed") from exc

    async def create_session(
        self, account_id: str, token_hash: str, expires_at: datetime
    ) -> SessionRecord:
        async with self._transaction() as session:
            row = SessionRow(
                account_id=uuid.UUID(account_id),
                token_hash=token_hash,
                expires_at=expires_at,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return self._session(row)

    async def get_session(self, token_hash: str) -> SessionRecord | None:
        try:
            async with self._sessions() as session:
                row = await session.scalar(
                    select(SessionRow).where(SessionRow.token_hash == token_hash)
                )
                return self._session(row) if row else None
        except SQLAlchemyError as exc:
            raise AuthRepositoryError("account database operation failed") from exc

    async def revoke_session(self, token_hash: str, revoked_at: datetime) -> None:
        async with self._transaction() as session:
            row = await session.scalar(
                select(SessionRow).where(SessionRow.token_hash == token_hash).with_for_update()
            )
            if row is not None and row.revoked_at is None:
                row.revoked_at = revoked_at

    async def create_entrant(
        self,
        account_id: str,
        tournament_id: str,
        kind: EntryKind,
        display_name: str,
    ) -> Entrant:
        async with self._transaction() as session:
            row = EntrantRow(
                account_id=uuid.UUID(account_id),
                tournament_id=tournament_id,
                kind=kind.value,
                display_name=display_name,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return self._entrant(row)

    async def get_entrant(self, account_id: str, tournament_id: str) -> Entrant | None:
        try:
            identifier = uuid.UUID(account_id)
        except ValueError:
            return None
        try:
            async with self._sessions() as session:
                row = await session.scalar(
                    select(EntrantRow).where(
                        EntrantRow.account_id == identifier,
                        EntrantRow.tournament_id == tournament_id,
                    )
                )
                return self._entrant(row) if row else None
        except SQLAlchemyError as exc:
            raise AuthRepositoryError("account database operation failed") from exc

    async def delete_entrant(self, entrant_id: str) -> None:
        async with self._transaction() as session:
            row = await self._locked_entrant(session, entrant_id)
            await session.delete(row)

    async def configure_bot(
        self,
        entrant_id: str,
        ip: str,
        port: int,
        token_ciphertext: str,
    ) -> Entrant:
        async with self._transaction() as session:
            row = await self._locked_entrant(session, entrant_id)
            if row.kind != EntryKind.BOT.value:
                raise AuthConflictError("human entrants cannot configure bot endpoints")
            row.bot_ip = ip
            row.bot_port = port
            row.bot_token_ciphertext = token_ciphertext
            row.bot_verified_at = None
            await session.flush()
            return self._entrant(row)

    async def mark_bot_verified(
        self,
        entrant_id: str,
        expected_token_ciphertext: str,
        verified_at: datetime,
    ) -> Entrant:
        async with self._transaction() as session:
            row = await self._locked_entrant(session, entrant_id)
            if row.bot_token_ciphertext != expected_token_ciphertext:
                raise AuthConflictError("bot endpoint changed during verification")
            row.bot_verified_at = verified_at
            await session.flush()
            return self._entrant(row)

    @staticmethod
    async def _locked_entrant(session: AsyncSession, entrant_id: str) -> EntrantRow:
        try:
            identifier = uuid.UUID(entrant_id)
        except ValueError as exc:
            raise AuthNotFoundError("entrant not found") from exc
        row = await session.scalar(
            select(EntrantRow).where(EntrantRow.id == identifier).with_for_update()
        )
        if row is None:
            raise AuthNotFoundError("entrant not found")
        return row

    @staticmethod
    def _account(row: AccountRow) -> Account:
        return Account(
            id=str(row.id),
            email=row.email,
            password_hash=row.password_hash,
            role=Role(row.role),
            created_at=row.created_at,
        )

    @staticmethod
    def _session(row: SessionRow) -> SessionRecord:
        return SessionRecord(
            id=str(row.id),
            account_id=str(row.account_id),
            token_hash=row.token_hash,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            created_at=row.created_at,
        )

    @staticmethod
    def _entrant(row: EntrantRow) -> Entrant:
        return Entrant(
            id=str(row.id),
            account_id=str(row.account_id),
            tournament_id=row.tournament_id,
            kind=EntryKind(row.kind),
            display_name=row.display_name,
            bot_ip=row.bot_ip,
            bot_port=row.bot_port,
            bot_token_ciphertext=row.bot_token_ciphertext,
            bot_verified_at=row.bot_verified_at,
            created_at=row.created_at,
        )
