from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network
from typing import Any

import httpx
import pytest

from poker_bot_platform.bots.conformance import conformance_request
from poker_bot_platform.bots.gateway import BotGateway
from poker_bot_platform.bots.models import BotEndpoint
from poker_bot_platform.domain.models import ActionType, FailureReason

ENDPOINT = BotEndpoint(ip="192.168.1.20", port=8001)
TOKEN = "test-bearer-token"


def valid_response(**updates: Any) -> dict[str, Any]:
    response: dict[str, Any] = {
        "protocol": "poker-bot.v1",
        "tournament_id": "conformance",
        "table_id": "table-1",
        "hand_id": "hand-1",
        "decision_id": "decision-1",
        "table_version": 1,
        "action": "check",
    }
    response.update(updates)
    return response


async def execute(handler: httpx.AsyncBaseTransport) -> Any:
    async with BotGateway(
        participant_subnet=ip_network("192.168.0.0/16"),
        transport=handler,
    ) as gateway:
        return await gateway.request_action(ENDPOINT, TOKEN, conformance_request())


@pytest.mark.asyncio
async def test_success_uses_fixed_path_bearer_token_and_no_proxy() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://192.168.1.20:8001/v1/action"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert request.headers["content-type"] == "application/json"
        body = json.loads(request.content)
        assert body["player"]["hole_cards"] == ["As", "Kd"]
        assert all("hole_cards" not in seat for seat in body["table"]["seats"])
        return httpx.Response(200, json=valid_response())

    outcome = await execute(httpx.MockTransport(handler))
    assert not outcome.used_fallback
    assert outcome.action.action is ActionType.CHECK


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (
            lambda _request: httpx.Response(503, json={"error": "down"}),
            FailureReason.HTTP_STATUS,
        ),
        (
            lambda _request: httpx.Response(200, text="ok", headers={"content-type": "text/plain"}),
            FailureReason.CONTENT_TYPE,
        ),
        (
            lambda _request: httpx.Response(
                200,
                content=b"x" * 4097,
                headers={"content-type": "application/json"},
            ),
            FailureReason.OVERSIZED,
        ),
        (
            lambda _request: httpx.Response(
                200,
                content=b"{not-json",
                headers={"content-type": "application/json"},
            ),
            FailureReason.MALFORMED_JSON,
        ),
        (
            lambda _request: httpx.Response(
                200,
                content=b'{"protocol":"poker-bot.v1","protocol":"bad"}',
                headers={"content-type": "application/json"},
            ),
            FailureReason.MALFORMED_JSON,
        ),
        (
            lambda _request: httpx.Response(200, json={"protocol": "poker-bot.v1"}),
            FailureReason.SCHEMA,
        ),
        (
            lambda _request: httpx.Response(302, headers={"location": "http://192.168.1.30/"}),
            FailureReason.HTTP_STATUS,
        ),
    ],
)
async def test_protocol_failure_matrix_uses_check_fallback(
    handler: Any,
    reason: FailureReason,
) -> None:
    outcome = await execute(httpx.MockTransport(handler))
    assert outcome.failure_reason is reason
    assert outcome.action.action is ActionType.CHECK
    assert outcome.response is None


@pytest.mark.asyncio
async def test_connection_and_timeout_failures_are_distinguished() -> None:
    def connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("late", request=request)

    connection_outcome = await execute(httpx.MockTransport(connection))
    timeout_outcome = await execute(httpx.MockTransport(timeout))
    assert connection_outcome.failure_reason is FailureReason.CONNECTION
    assert timeout_outcome.failure_reason is FailureReason.TIMEOUT


@pytest.mark.asyncio
async def test_gateway_revalidates_endpoint_at_the_outbound_boundary() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=valid_response())

    blocked_endpoint = BotEndpoint(ip="192.168.1.1", port=8001)
    async with BotGateway(
        participant_subnet=ip_network("192.168.0.0/16"),
        blocked_ips=("192.168.1.1",),
        transport=httpx.MockTransport(handler),
    ) as gateway:
        outcome = await gateway.request_action(
            blocked_endpoint,
            TOKEN,
            conformance_request(),
        )
    assert outcome.failure_reason is FailureReason.CONNECTION
    assert not called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (valid_response(decision_id="old"), FailureReason.STALE),
        (valid_response(table_version=0), FailureReason.STALE),
        (valid_response(action="call"), FailureReason.ILLEGAL_ACTION),
        (valid_response(action="raise", amount_to=399), FailureReason.ILLEGAL_ACTION),
        (valid_response(action="raise", amount_to=20_001), FailureReason.ILLEGAL_ACTION),
    ],
)
async def test_stale_or_illegal_response_is_rejected(
    response: dict[str, Any],
    reason: FailureReason,
) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=response))
    outcome = await execute(transport)
    assert outcome.failure_reason is reason
    assert outcome.action.action is ActionType.CHECK


@pytest.mark.asyncio
async def test_legal_raise_is_accepted() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json=valid_response(action="raise", amount_to=400),
        )
    )
    outcome = await execute(transport)
    assert outcome.failure_reason is None
    assert outcome.action.action is ActionType.RAISE
    assert outcome.action.amount_to == 400


@pytest.mark.asyncio
async def test_expired_request_is_not_dispatched() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=valid_response())

    request = conformance_request(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
    async with BotGateway(
        participant_subnet=ip_network("192.168.0.0/16"),
        transport=httpx.MockTransport(handler),
    ) as gateway:
        outcome = await gateway.request_action(ENDPOINT, TOKEN, request)
    assert outcome.failure_reason is FailureReason.TIMEOUT
    assert not called


@pytest.mark.asyncio
async def test_fallback_folds_when_check_is_not_legal() -> None:
    request_data = conformance_request().model_dump()
    request_data["legal_actions"] = [{"action": "fold"}, {"action": "call", "amount": 200}]
    request = type(conformance_request()).model_validate(request_data)
    transport = httpx.MockTransport(lambda _request: httpx.Response(503, json={}))
    async with BotGateway(
        participant_subnet=ip_network("192.168.0.0/16"),
        transport=transport,
    ) as gateway:
        outcome = await gateway.request_action(ENDPOINT, TOKEN, request)
    assert outcome.action.action is ActionType.FOLD
    assert outcome.failure_reason is FailureReason.HTTP_STATUS


@pytest.mark.asyncio
async def test_verification_requires_exact_challenge_echo() -> None:
    challenge = "c" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/verify"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(
            200,
            json={"protocol": "poker-bot.v1", "challenge": "x" * 32},
        )

    async with BotGateway(
        participant_subnet=ip_network("192.168.0.0/16"),
        transport=httpx.MockTransport(handler),
    ) as gateway:
        outcome = await gateway.verify(ENDPOINT, TOKEN, challenge)
    assert not outcome.verified
    assert outcome.failure_reason is FailureReason.STALE
