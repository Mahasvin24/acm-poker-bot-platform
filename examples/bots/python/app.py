"""Minimal FastAPI participant bot. Run with: uvicorn app:app --port 8001."""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI, Header, HTTPException

from poker_bot_platform.bots.models import (
    BotActionRequest,
    BotActionResponse,
    GameEndRequest,
    GameResponse,
    GameStartRequest,
    HealthResponse,
    VerifyRequest,
    VerifyResponse,
)
from strategy import choose_action

app = FastAPI()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "replace-me")
# Keep separate state for every match; one bot may play several matches.
games: dict[str, dict[str, int]] = {}


def authorize(authorization: str | None) -> None:
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme != "Bearer" or not secrets.compare_digest(presented, BOT_TOKEN):
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(protocol="poker-bot.v2", status="ready")


@app.post("/v1/verify", response_model=VerifyResponse)
async def verify(
    request: VerifyRequest,
    authorization: str | None = Header(default=None),
) -> VerifyResponse:
    authorize(authorization)
    return VerifyResponse(protocol="poker-bot.v2", challenge=request.challenge)


@app.post("/v1/game/start", response_model=GameResponse)
async def game_start(
    request: GameStartRequest,
    authorization: str | None = Header(default=None),
) -> GameResponse:
    authorize(authorization)
    # A repeated start (e.g. after a platform restart) must preserve existing state.
    games.setdefault(request.match_id, {})
    return GameResponse(
        protocol="poker-bot.v2", match_id=request.match_id, entrant_id=request.entrant_id
    )


@app.post("/v1/game/end", response_model=GameResponse)
async def game_end(
    request: GameEndRequest,
    authorization: str | None = Header(default=None),
) -> GameResponse:
    authorize(authorization)
    games.pop(request.match_id, None)
    return GameResponse(
        protocol="poker-bot.v2", match_id=request.match_id, entrant_id=request.entrant_id
    )


@app.post("/v1/action", response_model=BotActionResponse)
async def action(
    request: BotActionRequest,
    authorization: str | None = Header(default=None),
) -> BotActionResponse:
    authorize(authorization)
    # Recover if this bot restarted or missed the start notification.
    games.setdefault(request.match_id, {})
    selected, amount_to = choose_action(request)
    return BotActionResponse(
        protocol=request.protocol,
        match_id=request.match_id,
        table_id=request.table_id,
        hand_id=request.hand_id,
        decision_id=request.decision_id,
        table_version=request.table_version,
        action=selected,
        amount_to=amount_to,
    )
