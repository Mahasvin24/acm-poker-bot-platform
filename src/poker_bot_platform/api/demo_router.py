import re
import secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from poker_bot_platform.api.models import (
    DemoMatchStateResponse,
    PlayerActionRequest,
)
from poker_bot_platform.api.security import SameOriginGuard
from poker_bot_platform.integration.demo_match import (
    DemoMatchError,
    DemoMatchSessions,
    EphemeralDemoMatch,
)

DEMO_COOKIE = "poker_demo"
_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{22,64}$")


def create_demo_match_router(
    sessions: DemoMatchSessions,
    *,
    allowed_origin: str,
    cookie_secure: bool = False,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/demo-human-versus-bot", tags=["demo"])
    mutation_guard = [Depends(SameOriginGuard(allowed_origin))]

    async def session_match(
        response: Response,
        demo_session: Annotated[str | None, Cookie(alias=DEMO_COOKIE)] = None,
    ) -> EphemeralDemoMatch:
        if demo_session is None or not _SESSION_PATTERN.fullmatch(demo_session):
            demo_session = secrets.token_urlsafe(24)
            response.set_cookie(
                DEMO_COOKIE,
                demo_session,
                max_age=60 * 60,
                path="/api/v1/demo-human-versus-bot",
                secure=cookie_secure,
                httponly=True,
                samesite="lax",
            )
        return await sessions.get(demo_session)

    @router.get("", response_model=DemoMatchStateResponse)
    async def current_demo_match(
        demo: Annotated[EphemeralDemoMatch, Depends(session_match)],
    ) -> DemoMatchStateResponse:
        return await demo.current()

    @router.post(
        "/start",
        response_model=DemoMatchStateResponse,
        dependencies=mutation_guard,
    )
    async def start_demo_match(
        demo: Annotated[EphemeralDemoMatch, Depends(session_match)],
    ) -> DemoMatchStateResponse:
        return await demo.start()

    @router.post(
        "/action",
        response_model=DemoMatchStateResponse,
        dependencies=mutation_guard,
    )
    async def submit_demo_action(
        body: PlayerActionRequest,
        demo: Annotated[EphemeralDemoMatch, Depends(session_match)],
    ) -> DemoMatchStateResponse:
        try:
            return await demo.submit(body)
        except DemoMatchError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @router.post(
        "/end",
        response_model=DemoMatchStateResponse,
        dependencies=mutation_guard,
    )
    async def end_demo_match(
        demo: Annotated[EphemeralDemoMatch, Depends(session_match)],
    ) -> DemoMatchStateResponse:
        return await demo.end()

    return router
