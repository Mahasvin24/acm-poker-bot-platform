from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from poker_bot_platform.auth import AuthConflictError, SqlAlchemyAuthRepository
from poker_bot_platform.auth.service import hash_session_token
from poker_bot_platform.domain import EntryKind, Role
from poker_bot_platform.persistence import create_database

_DATABASE_URL = os.environ.get("POKER_TEST_DATABASE_URL")
_IS_SAFE_TEST_DATABASE = bool(
    _DATABASE_URL and (make_url(_DATABASE_URL).database or "").endswith("_test")
)
pytestmark = pytest.mark.skipif(
    not _IS_SAFE_TEST_DATABASE,
    reason="set POKER_TEST_DATABASE_URL to a dedicated database ending in _test",
)


@pytest.fixture(scope="module")
def migrated_auth_database() -> Iterator[str]:
    assert _DATABASE_URL is not None
    environment = {**os.environ, "POKER_DATABASE_URL": _DATABASE_URL}
    subprocess.run(
        ["python3", "-m", "alembic", "upgrade", "head"],
        check=True,
        env=environment,
    )
    yield _DATABASE_URL
    subprocess.run(
        ["python3", "-m", "alembic", "downgrade", "base"],
        check=True,
        env=environment,
    )


@pytest.mark.asyncio
async def test_postgres_auth_constraints_sessions_and_bot_round_trip(
    migrated_auth_database: str,
) -> None:
    suffix = uuid.uuid4().hex
    database, tables = create_database(migrated_auth_database)
    sessions = async_sessionmaker(database, class_=AsyncSession, expire_on_commit=False)
    repository = SqlAlchemyAuthRepository(sessions)
    tournament_id = f"auth-tournament-{suffix}"
    try:
        await tables.create_tournament(tournament_id, {"starting_stack": 20_000})
        account = await repository.create_account(
            f"{suffix}@example.com",
            "$argon2id$test-placeholder",
            Role.USER,
        )
        assert await repository.get_account_by_email(account.email) == account

        token_hash = hash_session_token(f"token-{suffix}")
        expiry = datetime.now(UTC) + timedelta(hours=1)
        created_session = await repository.create_session(account.id, token_hash, expiry)
        assert await repository.get_session(token_hash) == created_session
        await repository.revoke_session(token_hash, datetime.now(UTC))
        revoked = await repository.get_session(token_hash)
        assert revoked is not None
        assert revoked.revoked_at is not None

        results = await asyncio.gather(
            repository.create_entrant(
                account.id,
                tournament_id,
                EntryKind.BOT,
                "Concurrent Bot",
            ),
            repository.create_entrant(
                account.id,
                tournament_id,
                EntryKind.BOT,
                "Concurrent Bot",
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert sum(isinstance(result, AuthConflictError) for result in results) == 1

        entrant = await repository.get_entrant(account.id, tournament_id)
        assert entrant is not None
        configured = await repository.configure_bot(
            entrant.id,
            "192.168.1.25",
            8001,
            "encrypted-token",
        )
        verified = await repository.mark_bot_verified(
            configured.id,
            "encrypted-token",
            datetime.now(UTC),
        )
        assert verified.bot_verified_at is not None

        with pytest.raises(AuthConflictError):
            await repository.create_entrant(
                account.id,
                f"missing-{suffix}",
                EntryKind.HUMAN,
                "Missing Tournament",
            )
    finally:
        await database.dispose()
