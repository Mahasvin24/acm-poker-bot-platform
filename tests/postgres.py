from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from poker_bot_platform.domain import MatchConfig
from poker_bot_platform.match import MatchState

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def postgres_database_url() -> str | None:
    """Database used by live-Postgres tests (same as the app unless overridden)."""
    return os.environ.get("POKER_TEST_DATABASE_URL") or os.environ.get("POKER_DATABASE_URL")


def _postgres_skip_reason() -> str | None:
    if postgres_database_url():
        return None
    return (
        "set POKER_DATABASE_URL in the repo root .env (same URL the app uses) "
        "or override with POKER_TEST_DATABASE_URL"
    )


requires_postgres = pytest.mark.skipif(
    _postgres_skip_reason() is not None,
    reason=_postgres_skip_reason() or "postgres tests unavailable",
)


async def _reset_schema(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def _alembic_upgrade(url: str) -> None:
    subprocess.run(
        ["python3", "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "POKER_DATABASE_URL": url},
    )


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[str]:
    url = postgres_database_url()
    assert url is not None
    asyncio.run(_reset_schema(url))
    _alembic_upgrade(url)
    yield url
    asyncio.run(_reset_schema(url))
    _alembic_upgrade(url)


def lobby_state(match_id: str, *, join_code: str = "ABCDEF") -> MatchState:
    return MatchState(
        match_id=match_id,
        name="Postgres test",
        join_code=join_code,
        config=MatchConfig(),
        seed_hex="0" * 64,
        created_by="admin",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
