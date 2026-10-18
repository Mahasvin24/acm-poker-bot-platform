from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from poker_bot_platform import __version__
from poker_bot_platform.api.demo_router import create_demo_match_router
from poker_bot_platform.api.router import create_api_router
from poker_bot_platform.auth.service import AuthService, BotProfileService
from poker_bot_platform.auth.sqlalchemy import SqlAlchemyAuthRepository
from poker_bot_platform.bots import BotGateway
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.config import Settings
from poker_bot_platform.integration import GameplayScheduler, MatchRuntime, MatchService
from poker_bot_platform.integration.demo_match import DemoMatchSessions
from poker_bot_platform.match import MatchRegistry, SqlAlchemyMatchStore
from poker_bot_platform.persistence import create_database_components


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    database_engine, sessions, table_repository = create_database_components(settings.database_url)
    auth_repository = SqlAlchemyAuthRepository(sessions)
    registry = MatchRegistry(SqlAlchemyMatchStore(sessions))
    bot_gateway = BotGateway(
        participant_subnet=settings.participant_subnet,
        blocked_ips=settings.blocked_ips,
    )
    auth = AuthService(auth_repository)
    token_store = EncryptedTokenStore.from_deployment_secret(settings.secret_key.get_secret_value())
    bots = BotProfileService(
        auth_repository,
        token_store=token_store,
        participant_subnet=settings.participant_subnet,
        blocked_ips=settings.blocked_ips,
        verifier=bot_gateway,
    )
    runtime = MatchRuntime(
        registry,
        table_repository,
        auth_repository,
        token_store,
        bot_gateway,
    )
    matches = MatchService(registry, auth_repository, bots, bot_gateway, runtime)
    scheduler = GameplayScheduler(registry, runtime)
    demo_match = DemoMatchSessions()

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        await scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()
            await demo_match.aclose()
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
            bots=bots,
            matches=matches,
            runtime=runtime,
            allowed_origin=settings.allowed_origin,
            cookie_secure=settings.cookie_secure,
        )
    )
    application.include_router(
        create_demo_match_router(
            demo_match,
            allowed_origin=settings.allowed_origin,
            cookie_secure=settings.cookie_secure,
        )
    )
    application.state.database_engine = database_engine
    application.state.match_registry = registry
    application.state.gameplay_runtime = runtime
    application.state.gameplay_scheduler = scheduler
    application.state.demo_match = demo_match
    return application


def __getattr__(name: str) -> FastAPI:
    # Built on first access so importing create_app never requires deployment settings.
    if name != "app":
        raise AttributeError(name)
    application = create_app()
    globals()["app"] = application
    return application
