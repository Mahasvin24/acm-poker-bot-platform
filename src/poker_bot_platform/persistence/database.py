from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from poker_bot_platform.persistence.sqlalchemy import SqlAlchemyTableRepository


def create_database(database_url: str) -> tuple[AsyncEngine, SqlAlchemyTableRepository]:
    engine, _sessions, repository = create_database_components(database_url)
    return engine, repository


def create_database_components(
    database_url: str,
) -> tuple[
    AsyncEngine,
    async_sessionmaker[AsyncSession],
    SqlAlchemyTableRepository,
]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, sessions, SqlAlchemyTableRepository(sessions)
