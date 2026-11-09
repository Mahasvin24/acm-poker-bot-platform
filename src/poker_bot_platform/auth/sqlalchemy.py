from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from poker_bot_platform.auth.career import match_result_rows
from poker_bot_platform.auth.db_models import (
    AccountRow,
    BotProfileRow,
    MatchAccountResultRow,
    PasswordResetRequestRow,
    SessionRow,
)
from poker_bot_platform.auth.models import (
    Account,
    BotProfile,
    CareerSummary,
    LeaderboardEntry,
    MatchResultSummary,
    PasswordResetRequest,
    SessionRecord,
)
from poker_bot_platform.auth.repository import (
    AuthConflictError,
    AuthNotFoundError,
    AuthRepositoryError,
)
from poker_bot_platform.domain import EntryKind, Role
from poker_bot_platform.match.models import MatchState


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

    async def create_account(
        self, email: str, password_hash: str, role: Role,
        participant_kind: EntryKind | None = None,
    ) -> Account:
        async with self._transaction() as session:
            row = AccountRow(
                email=email, password_hash=password_hash, role=role.value,
                participant_kind=participant_kind.value if participant_kind else None,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return self._account(row)

    async def get_account_by_email(self, email: str) -> Account | None:
        async with self._read() as session:
            row = await session.scalar(
                select(AccountRow).where(
                    AccountRow.email == email,
                    AccountRow.deleted_at.is_(None),
                )
            )
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
            raise AuthConflictError("you already have a bot; edit its settings instead") from exc

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

    async def update_account_profile(
        self, account_id: str, *, display_name: str | None
    ) -> Account:
        identifier = _uuid_or_none(account_id)
        async with self._transaction() as session:
            row = await session.get(AccountRow, identifier) if identifier else None
            if row is None or row.deleted_at is not None:
                raise AuthNotFoundError("account not found")
            row.display_name = display_name
            await session.flush()
            return self._account(row)

    async def change_account_email(self, account_id: str, email: str) -> Account:
        identifier = _uuid_or_none(account_id)
        async with self._transaction() as session:
            row = await session.get(AccountRow, identifier) if identifier else None
            if row is None or row.deleted_at is not None:
                raise AuthNotFoundError("account not found")
            taken = await session.scalar(
                select(AccountRow.id).where(
                    AccountRow.email == email,
                    AccountRow.id != identifier,
                )
            )
            if taken is not None:
                raise AuthConflictError("that email is already registered")
            row.email = email
            await session.flush()
            return self._account(row)

    async def delete_account(self, account_id: str, deleted_at: datetime) -> Account:
        identifier = _uuid_or_none(account_id)
        async with self._transaction() as session:
            row = await session.get(AccountRow, identifier) if identifier else None
            if row is None or row.deleted_at is not None:
                raise AuthNotFoundError("account not found")
            row.deleted_at = deleted_at
            await session.execute(
                update(SessionRow)
                .where(SessionRow.account_id == identifier, SessionRow.revoked_at.is_(None))
                .values(revoked_at=deleted_at)
            )
            await session.flush()
            return self._account(row)

    async def upsert_password_reset_request(self, account_id: str) -> None:
        identifier = _uuid_or_none(account_id)
        if identifier is None:
            return
        async with self._transaction() as session:
            row = await session.get(AccountRow, identifier)
            if row is None or row.deleted_at is not None:
                return
            existing = await session.scalar(
                select(PasswordResetRequestRow)
                .where(
                    PasswordResetRequestRow.account_id == identifier,
                    PasswordResetRequestRow.fulfilled_at.is_(None),
                )
                .with_for_update()
            )
            if existing is None:
                session.add(PasswordResetRequestRow(account_id=identifier))

    async def list_password_reset_requests(self) -> tuple[PasswordResetRequest, ...]:
        async with self._read() as session:
            result = await session.execute(
                select(PasswordResetRequestRow, AccountRow.email)
                .join(AccountRow, AccountRow.id == PasswordResetRequestRow.account_id)
                .where(PasswordResetRequestRow.fulfilled_at.is_(None))
                .order_by(PasswordResetRequestRow.created_at.desc())
            )
            return tuple(
                PasswordResetRequest(
                    account_id=str(row.account_id),
                    email=email,
                    requested_at=row.created_at,
                )
                for row, email in result.all()
            )

    async def fulfill_password_reset_requests(self, account_id: str, fulfilled_at: datetime) -> None:
        identifier = _uuid_or_none(account_id)
        if identifier is None:
            return
        async with self._transaction() as session:
            await session.execute(
                update(PasswordResetRequestRow)
                .where(
                    PasswordResetRequestRow.account_id == identifier,
                    PasswordResetRequestRow.fulfilled_at.is_(None),
                )
                .values(fulfilled_at=fulfilled_at)
            )

    async def record_match_completion(self, state: MatchState) -> None:
        async with self._transaction() as session:
            await self.record_match_completion_in_session(session, state)

    async def record_match_completion_in_session(
        self, session: AsyncSession, state: MatchState
    ) -> None:
        for row in match_result_rows(state):
            exists = await session.scalar(
                select(MatchAccountResultRow.id).where(
                    MatchAccountResultRow.match_id == row.match_id,
                    MatchAccountResultRow.entry_id == row.entry_id,
                )
            )
            if exists is not None:
                continue
            session.add(
                MatchAccountResultRow(
                    match_id=row.match_id,
                    account_id=uuid.UUID(row.account_id),
                    entry_id=row.entry_id,
                    match_name=row.match_name,
                    display_name=row.display_name,
                    kind=row.kind.value,
                    position=row.position,
                    starting_stack=state.config.starting_stack,
                    final_stack=row.final_stack,
                    chip_delta=row.chip_delta,
                )
            )

    async def career_summary(self, account_id: str) -> CareerSummary:
        identifier = _uuid_or_none(account_id)
        if identifier is None:
            return CareerSummary()
        async with self._read() as session:
            totals = await session.execute(
                select(
                    func.coalesce(func.sum(MatchAccountResultRow.chip_delta), 0),
                    func.count(func.distinct(MatchAccountResultRow.match_id)),
                ).where(MatchAccountResultRow.account_id == identifier)
            )
            chips, matches = totals.one()
            return CareerSummary(
                career_chip_total=int(chips or 0),
                matches_finished=int(matches or 0),
            )

    async def match_results_for_account(self, account_id: str) -> tuple[MatchResultSummary, ...]:
        identifier = _uuid_or_none(account_id)
        if identifier is None:
            return ()
        async with self._read() as session:
            rows = await session.scalars(
                select(MatchAccountResultRow)
                .where(MatchAccountResultRow.account_id == identifier)
                .order_by(MatchAccountResultRow.recorded_at.desc())
            )
            return tuple(self._match_result(row) for row in rows)

    async def leaderboard(self, *, limit: int = 50) -> tuple[LeaderboardEntry, ...]:
        async with self._read() as session:
            totals = await session.execute(
                select(
                    MatchAccountResultRow.account_id,
                    func.coalesce(func.sum(MatchAccountResultRow.chip_delta), 0),
                    func.count(func.distinct(MatchAccountResultRow.match_id)),
                )
                .group_by(MatchAccountResultRow.account_id)
                .order_by(func.sum(MatchAccountResultRow.chip_delta).desc())
                .limit(limit)
            )
            entries: list[LeaderboardEntry] = []
            for account_uuid, chips, matches in totals.all():
                account = await session.get(AccountRow, account_uuid)
                if account is None or account.deleted_at is not None:
                    continue
                entries.append(
                    LeaderboardEntry(
                        account_id=str(account_uuid),
                        email=account.email,
                        display_name=account.display_name,
                        career_chip_total=int(chips or 0),
                        matches_finished=int(matches or 0),
                    )
                )
            return tuple(entries)

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
            participant_kind=EntryKind(row.participant_kind) if row.participant_kind else None,
            display_name=row.display_name,
            deleted_at=row.deleted_at,
            created_at=row.created_at,
        )

    @staticmethod
    def _match_result(row: MatchAccountResultRow) -> MatchResultSummary:
        from poker_bot_platform.domain import EntryKind

        return MatchResultSummary(
            account_id=str(row.account_id),
            entry_id=row.entry_id,
            match_id=row.match_id,
            match_name=row.match_name,
            position=row.position,
            final_stack=row.final_stack,
            chip_delta=row.chip_delta,
            display_name=row.display_name,
            kind=EntryKind(row.kind),
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
