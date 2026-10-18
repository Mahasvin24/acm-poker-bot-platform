from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from poker_bot_platform.auth import AuthConflictError, SqlAlchemyAuthRepository
from poker_bot_platform.auth.service import hash_session_token
from poker_bot_platform.domain import Role
from poker_bot_platform.persistence import create_database_components

from ..postgres import migrated_database, requires_postgres

pytestmark = requires_postgres
__all__ = ["migrated_database"]


@pytest.mark.asyncio
async def test_postgres_auth_constraints_sessions_and_bot_profiles(
    migrated_database: str,
) -> None:
    suffix = uuid.uuid4().hex
    database, sessions, _tables = create_database_components(migrated_database)
    repository = SqlAlchemyAuthRepository(sessions)
    try:
        account = await repository.create_account(
            f"{suffix}@example.com",
            "$argon2id$test-placeholder",
            Role.USER,
        )
        assert await repository.get_account_by_email(account.email) == account
        assert account in await repository.list_accounts()

        token_hash = hash_session_token(f"token-{suffix}")
        expiry = datetime.now(UTC) + timedelta(hours=1)
        created_session = await repository.create_session(account.id, token_hash, expiry)
        assert await repository.get_session(token_hash) == created_session
        await repository.revoke_account_sessions(account.id, datetime.now(UTC))
        revoked = await repository.get_session(token_hash)
        assert revoked is not None
        assert revoked.revoked_at is not None

        updated = await repository.set_password_hash(account.id, "$argon2id$replacement")
        assert updated.password_hash == "$argon2id$replacement"

        results = await asyncio.gather(
            repository.create_bot_profile(account.id, "Same Name", "192.168.1.25", 8001, "a"),
            repository.create_bot_profile(account.id, "same name", "192.168.1.26", 8002, "b"),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert sum(isinstance(result, AuthConflictError) for result in results) == 1

        profile = next(result for result in results if not isinstance(result, BaseException))
        verified = await repository.record_bot_verification(
            profile.id,
            profile.bot_token_ciphertext,
            verified_at=datetime.now(UTC),
            error=None,
        )
        assert verified.verified_at is not None
        moved = await repository.update_bot_profile(profile.id, ip="192.168.1.40")
        assert moved.verified_at is None
        assert moved.bot_ip == "192.168.1.40"
        with pytest.raises(AuthConflictError):
            await repository.record_bot_verification(
                profile.id, "stale-ciphertext", verified_at=datetime.now(UTC), error=None
            )
        assert await repository.list_bot_profiles(account.id) == (moved,)
        await repository.delete_bot_profile(profile.id)
        assert await repository.get_bot_profile(profile.id) is None
    finally:
        await database.dispose()
