from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from poker_bot_platform.domain import MatchConfig
from poker_bot_platform.match import MatchState

DATABASE_URL = os.environ.get("POKER_TEST_DATABASE_URL")
IS_SAFE_TEST_DATABASE = bool(
    DATABASE_URL and (make_url(DATABASE_URL).database or "").endswith("_test")
)
requires_postgres = pytest.mark.skipif(
    not IS_SAFE_TEST_DATABASE,
    reason="set POKER_TEST_DATABASE_URL to a dedicated database ending in _test",
)


async def _reset_schema(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[str]:
    assert DATABASE_URL is not None
    asyncio.run(_reset_schema(DATABASE_URL))
    subprocess.run(
        ["python3", "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "POKER_DATABASE_URL": DATABASE_URL},
    )
    yield DATABASE_URL
    asyncio.run(_reset_schema(DATABASE_URL))


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
