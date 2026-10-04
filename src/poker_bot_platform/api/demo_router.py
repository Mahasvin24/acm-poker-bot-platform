from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status

from poker_bot_platform.api.models import (
    DemoMatchStateResponse,
    PlayerActionRequest,
)
from poker_bot_platform.api.security import SameOriginGuard
from poker_bot_platform.integration.demo_match import DemoMatchError, EphemeralDemoMatch


def create_demo_match_router(
    demo_match: EphemeralDemoMatch,
    *,
    allowed_origin: str,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/demo-human-versus-bot", tags=["demo"])
    mutation_guard = [Depends(SameOriginGuard(allowed_origin))]

    @router.get("", response_model=DemoMatchStateResponse)
    async def current_demo_match() -> DemoMatchStateResponse:
        return await demo_match.current()

    @router.post(
        "/start",
        response_model=DemoMatchStateResponse,
        dependencies=mutation_guard,
    )
    async def start_demo_match() -> DemoMatchStateResponse:
        return await demo_match.start()

    @router.post(
        "/action",
        response_model=DemoMatchStateResponse,
        dependencies=mutation_guard,
    )
    async def submit_demo_action(body: PlayerActionRequest) -> DemoMatchStateResponse:
        try:
            return await demo_match.submit(body)
        except DemoMatchError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    @router.post(
        "/cheat/{outcome}",
        response_model=DemoMatchStateResponse,
        dependencies=mutation_guard,
    )
    async def force_demo_outcome(
        outcome: Literal["human_win", "bot_win"],
    ) -> DemoMatchStateResponse:
        try:
            return await demo_match.force(outcome)
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
    async def end_demo_match() -> DemoMatchStateResponse:
        return await demo_match.end()

    return router
