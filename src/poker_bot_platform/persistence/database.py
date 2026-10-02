from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from poker_bot_platform.persistence.sqlalchemy import SqlAlchemyTableRepository


def create_database(database_url: str) -> tuple[AsyncEngine, SqlAlchemyTableRepository]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, SqlAlchemyTableRepository(sessions)
