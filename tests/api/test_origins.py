from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

from poker_bot_platform.api.security import SameOriginGuard

ORIGINS = "http://localhost:3000, http://127.0.0.1:3000, http://192.168.0.176:3000"


@pytest.mark.parametrize("origin", ORIGINS.replace(" ", "").split(","))
async def test_configured_local_and_lan_origins_are_allowed(origin: str) -> None:
    request = Request({"type": "http", "method": "POST", "headers": [(b"origin", origin.encode())]})
    await SameOriginGuard(ORIGINS)(request)


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "https://unrelated.example",
        "http://192.168.0.176:3001",
        "http://localhost:3000.attacker.example",
        "http://localhost:3000/path",
    ],
)
async def test_unconfigured_and_missing_origins_remain_blocked(origin: str | None) -> None:
    headers = [(b"origin", origin.encode())] if origin else []
    request = Request({"type": "http", "method": "POST", "headers": headers})
    with pytest.raises(HTTPException) as error:
        await SameOriginGuard(ORIGINS)(request)
    assert error.value.status_code == 403


async def test_single_origin_configuration_stays_compatible() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"origin", b"http://localhost:3000")],
        }
    )
    await SameOriginGuard("http://localhost:3000")(request)
