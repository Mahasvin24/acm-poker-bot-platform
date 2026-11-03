from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from poker_bot_platform.auth.db_models import AccountRow, BotProfileRow, SessionRow
from poker_bot_platform.auth.models import Account, BotProfile, SessionRecord
from poker_bot_platform.auth.repository import (
    AuthConflictError,
    AuthNotFoundError,
    AuthRepositoryError,
)
from poker_bot_platform.domain import Role


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


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
            raise AuthConflictError("account or bot constraint was violated") from exc
        except SQLAlchemyError as exc:
            raise AuthRepositoryError("account database operation failed") from exc

    @asynccontextmanager
    async def _read(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self._sessions() as session:
                yield session
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
        async with self._read() as session:
            row = await session.scalar(select(AccountRow).where(AccountRow.email == email))
            return self._account(row) if row else None

    async def get_account(self, account_id: str) -> Account | None:
        identifier = _uuid_or_none(account_id)
        if identifier is None:
            return None
        async with self._read() as session:
            row = await session.get(AccountRow, identifier)
            return self._account(row) if row else None

    async def list_accounts(self) -> tuple[Account, ...]:
        async with self._read() as session:
            rows = await session.scalars(select(AccountRow).order_by(AccountRow.created_at))
            return tuple(self._account(row) for row in rows)

    async def set_password_hash(self, account_id: str, password_hash: str) -> Account:
        identifier = _uuid_or_none(account_id)
        async with self._transaction() as session:
            row = await session.get(AccountRow, identifier) if identifier else None
            if row is None:
                raise AuthNotFoundError("account not found")
            row.password_hash = password_hash
            await session.flush()
            return self._account(row)

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
        async with self._read() as session:
            row = await session.scalar(
                select(SessionRow).where(SessionRow.token_hash == token_hash)
            )
            return self._session(row) if row else None

    async def revoke_session(self, token_hash: str, revoked_at: datetime) -> None:
        async with self._transaction() as session:
            row = await session.scalar(
                select(SessionRow).where(SessionRow.token_hash == token_hash).with_for_update()
            )
            if row is not None and row.revoked_at is None:
                row.revoked_at = revoked_at

    async def revoke_account_sessions(self, account_id: str, revoked_at: datetime) -> None:
        identifier = _uuid_or_none(account_id)
        if identifier is None:
            return
        async with self._transaction() as session:
            await session.execute(
                update(SessionRow)
                .where(SessionRow.account_id == identifier, SessionRow.revoked_at.is_(None))
                .values(revoked_at=revoked_at)
            )

    async def create_bot_profile(
        self,
        account_id: str,
        name: str,
        ip: str,
        port: int,
        token_ciphertext: str,
    ) -> BotProfile:
        try:
            async with self._transaction() as session:
                row = BotProfileRow(
                    account_id=uuid.UUID(account_id),
                    name=name,
                    bot_ip=ip,
                    bot_port=port,
                    bot_token_ciphertext=token_ciphertext,
                )
                session.add(row)
                await session.flush()
                await session.refresh(row)
                return self._bot_profile(row)
        except AuthConflictError as exc:
            raise AuthConflictError("you already have a bot with that name") from exc

    async def get_bot_profile(self, profile_id: str) -> BotProfile | None:
        identifier = _uuid_or_none(profile_id)
        if identifier is None:
            return None
        async with self._read() as session:
            row = await session.get(BotProfileRow, identifier)
            return self._bot_profile(row) if row else None

    async def list_bot_profiles(self, account_id: str) -> tuple[BotProfile, ...]:
        identifier = _uuid_or_none(account_id)
        if identifier is None:
            return ()
        async with self._read() as session:
            rows = await session.scalars(
                select(BotProfileRow)
                .where(BotProfileRow.account_id == identifier)
                .order_by(BotProfileRow.created_at)
            )
            return tuple(self._bot_profile(row) for row in rows)

    async def update_bot_profile(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        ip: str | None = None,
        port: int | None = None,
        token_ciphertext: str | None = None,
    ) -> BotProfile:
        try:
            async with self._transaction() as session:
                row = await self._locked_profile(session, profile_id)
                if name is not None:
                    row.name = name
                if ip is not None or port is not None or token_ciphertext is not None:
                    row.verified_at = None
                    row.last_verification_error = None
                if ip is not None:
                    row.bot_ip = ip
                if port is not None:
                    row.bot_port = port
                if token_ciphertext is not None:
                    row.bot_token_ciphertext = token_ciphertext
                await session.flush()
                return self._bot_profile(row)
        except AuthConflictError as exc:
            if isinstance(exc.__cause__, IntegrityError):
                raise AuthConflictError("you already have a bot with that name") from exc
            raise

    async def record_bot_verification(
        self,
        profile_id: str,
        expected_token_ciphertext: str,
        *,
        verified_at: datetime | None,
        error: str | None,
    ) -> BotProfile:
        async with self._transaction() as session:
            row = await self._locked_profile(session, profile_id)
            if row.bot_token_ciphertext != expected_token_ciphertext:
                raise AuthConflictError("bot endpoint changed during verification")
            row.verified_at = verified_at
            row.last_verification_error = error
            await session.flush()
            return self._bot_profile(row)

    async def delete_bot_profile(self, profile_id: str) -> None:
        async with self._transaction() as session:
            row = await self._locked_profile(session, profile_id)
            await session.delete(row)

    @staticmethod
    async def _locked_profile(session: AsyncSession, profile_id: str) -> BotProfileRow:
        identifier = _uuid_or_none(profile_id)
        if identifier is None:
            raise AuthNotFoundError("bot not found")
        row = await session.scalar(
            select(BotProfileRow).where(BotProfileRow.id == identifier).with_for_update()
        )
        if row is None:
            raise AuthNotFoundError("bot not found")
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
    def _bot_profile(row: BotProfileRow) -> BotProfile:
        return BotProfile(
            id=str(row.id),
            account_id=str(row.account_id),
            name=row.name,
            bot_ip=row.bot_ip,
            bot_port=row.bot_port,
            bot_token_ciphertext=row.bot_token_ciphertext,
            verified_at=row.verified_at,
            last_verification_error=row.last_verification_error,
            created_at=row.created_at,
        )
