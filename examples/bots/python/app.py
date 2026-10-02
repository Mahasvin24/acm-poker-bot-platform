"""Minimal FastAPI participant bot. Run with: uvicorn app:app --port 8001."""

from __future__ import annotations

import os
import secrets

from fastapi import FastAPI, Header, HTTPException

from poker_bot_platform.bots.models import (
    BotActionRequest,
    BotActionResponse,
    HealthResponse,
    VerifyRequest,
    VerifyResponse,
)
from poker_bot_platform.bots.reference import deterministic_reference_action

app = FastAPI()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "replace-me")


def authorize(authorization: str | None) -> None:
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme != "Bearer" or not secrets.compare_digest(presented, BOT_TOKEN):
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(protocol="poker-bot.v1", status="ready")


@app.post("/v1/verify", response_model=VerifyResponse)
async def verify(
    request: VerifyRequest,
    authorization: str | None = Header(default=None),
) -> VerifyResponse:
    authorize(authorization)
    return VerifyResponse(protocol="poker-bot.v1", challenge=request.challenge)


@app.post("/v1/action", response_model=BotActionResponse)
async def action(
    request: BotActionRequest,
    authorization: str | None = Header(default=None),
) -> BotActionResponse:
    authorize(authorization)
    return deterministic_reference_action(request)
