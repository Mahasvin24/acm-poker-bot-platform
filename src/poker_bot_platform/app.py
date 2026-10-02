from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from poker_bot_platform import __version__
from poker_bot_platform.api import create_api_router
from poker_bot_platform.auth.service import AuthService, EntrantService
from poker_bot_platform.auth.sqlalchemy import SqlAlchemyAuthRepository
from poker_bot_platform.bots import BotGateway
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.config import Settings
from poker_bot_platform.integration import (
    AdminCoordinatorService,
    HeadlessGameplayRuntime,
    RuntimeAdminCoordinatorService,
    SyncedEntrantService,
    TournamentRegistry,
)
from poker_bot_platform.persistence import create_database_components
from poker_bot_platform.tournament import SqlAlchemyTournamentStore


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    database_engine, sessions, table_repository = create_database_components(settings.database_url)
    auth_repository = SqlAlchemyAuthRepository(sessions)
    tournament_store = SqlAlchemyTournamentStore(sessions)
    registry = TournamentRegistry(tournament_store, table_repository)
    bot_gateway = BotGateway(
        participant_subnet=settings.participant_subnet,
        blocked_ips=settings.blocked_ips,
    )
    auth = AuthService(auth_repository)
    token_store = EncryptedTokenStore.from_deployment_secret(settings.secret_key.get_secret_value())
    entrant_accounts = EntrantService(
        auth_repository,
        token_store=token_store,
        participant_subnet=settings.participant_subnet,
        blocked_ips=settings.blocked_ips,
        verifier=bot_gateway,
    )
    entrants = SyncedEntrantService(entrant_accounts, registry)
    gameplay = HeadlessGameplayRuntime(
        registry,
        table_repository,
        auth_repository,
        token_store,
        bot_gateway,
    )
    admin = RuntimeAdminCoordinatorService(
        AdminCoordinatorService(registry),
        gameplay,
        registry,
    )

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        yield
        await bot_gateway.aclose()
        await database_engine.dispose()

    application = FastAPI(
        title="ACM Poker Bot Platform",
        version=__version__,
        lifespan=lifespan,
    )

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    application.include_router(
        create_api_router(
            auth=auth,
            entrants=entrants,
            admin=admin,
            gameplay=gameplay,
            allowed_origin=settings.allowed_origin,
            cookie_secure=settings.cookie_secure,
        )
    )
    application.state.database_engine = database_engine
    application.state.tournament_registry = registry
    application.state.gameplay_runtime = gameplay
    return application


app = create_app()
