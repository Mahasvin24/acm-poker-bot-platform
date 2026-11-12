from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from ipaddress import ip_network

import httpx
import pytest
from fastapi import FastAPI

from poker_bot_platform.api.router import create_api_router
from poker_bot_platform.auth.models import Account
from poker_bot_platform.auth.repository import AuthNotFoundError
from poker_bot_platform.bots import BotGateway
from poker_bot_platform.bots.models import BotActionRequest
from poker_bot_platform.domain import EntryKind
from poker_bot_platform.integration.bot_testing import BotTestBusyError, BotTestingService
from poker_bot_platform.integration.matches import MatchCommandError

from .match_stack import MatchStack, build_stack


class BotServer:
    def __init__(self) -> None:
        self.mode = "valid"
        self.token = ""
        self.requests: list[httpx.Request] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.started.set()
        if self.mode == "blocked":
            await self.release.wait()
        if request.url.path == "/v1/health":
            return httpx.Response(
                200,
                json={
                    "protocol": "poker-bot.v2",
                    "status": "broken" if self.mode == "health_bad" else "ready",
                },
            )
        assert request.headers["authorization"] == f"Bearer {self.token}"
        if request.url.path == "/v1/verify":
            body = json.loads(request.content)
            if self.mode == "verify_bad":
                body["challenge"] = "w" * 32
            return httpx.Response(200, json=body)
        payload = BotActionRequest.model_validate_json(request.content)
        if self.mode == "timeout":
            raise httpx.ReadTimeout(f"sensitive internal detail {self.token}")
        if self.mode == "malformed":
            return httpx.Response(
                200, text="{bad json", headers={"content-type": "application/json"}
            )
        if self.mode == "oversized":
            return httpx.Response(200, json={"secret": self.token, "padding": "x" * 5000})
        legal = {item.action.value: item for item in payload.legal_actions}
        action = "raise" if "raise" in legal else "call"
        amount = legal["raise"].min_amount_to if action == "raise" else None
        if self.mode == "raise_low":
            action, amount = "raise", 1
        if self.mode == "raise_high":
            action, amount = "raise", 1_000_000
        response = {
            "protocol": "poker-bot.v2",
            "match_id": payload.match_id,
            "table_id": payload.table_id,
            "hand_id": payload.hand_id,
            "decision_id": "old" if self.mode == "stale" else payload.decision_id,
            "table_version": payload.table_version,
            "action": action,
            "amount_to": amount,
        }
        return httpx.Response(200, json=response)


@dataclass
class TestStack:
    __test__ = False
    platform: MatchStack
    tester: BotTestingService
    owner: Account
    bot_id: str
    server: BotServer
    app: FastAPI


@pytest.fixture
async def stack() -> AsyncIterator[TestStack]:
    platform = await build_stack()
    owner = await platform.user("bot@example.com")
    created = await platform.bots.create(owner.id, "Test Bot", "10.20.0.20", 8001)
    platform.network.tokens["10.20.0.20"] = created.bearer_token
    server = BotServer()
    server.token = created.bearer_token
    async with BotGateway(
        participant_subnet=ip_network("10.20.0.0/24"), transport=httpx.MockTransport(server)
    ) as gateway:
        tester = BotTestingService(platform.matches, gateway)
        app = FastAPI()
        app.include_router(
            create_api_router(
                auth=platform.auth,
                bots=platform.bots,
                matches=platform.matches,
                runtime=platform.runtime,
                bot_testing=tester,
                allowed_origin="http://testserver",
            )
        )
        yield TestStack(platform, tester, owner, created.profile.id, server, app)
    await platform.gateway.aclose()


async def prepare_match(stack: TestStack):
    p = stack.platform
    await p.bots.verify(stack.owner.id, stack.bot_id)
    match_id, code = await p.create_match()
    await p.matches.join(stack.owner, code, EntryKind.BOT, None, stack.bot_id)
    human = await p.user("human@example.com")
    await p.join_human(human, code, "Human")
    return match_id


async def test_successful_suite_is_bounded_private_and_does_not_verify_or_change_state(stack):
    before = await stack.platform.bots.get(stack.owner.id, stack.bot_id)
    report = await stack.tester.run(stack.owner.id, stack.bot_id)
    assert report.passed
    assert len(report.checks) == len(stack.server.requests) == 6
    assert [item.action.value if item.action else None for item in report.checks] == [
        None,
        None,
        "raise",
        "raise",
        "call",
        "raise",
    ]
    assert report.checks[-1].amount_to == 900
    assert await stack.platform.bots.get(stack.owner.id, stack.bot_id) == before
    assert before.verified_at is None
    assert stack.server.token not in report.model_dump_json()
    assert before.bot_token_ciphertext not in report.model_dump_json()
    assert all(len(request.content) < 64 * 1024 for request in stack.server.requests)


@pytest.mark.parametrize(
    "mode,message",
    [
        ("raise_low", "out of bounds"),
        ("raise_high", "out of bounds"),
        ("stale", "identifiers"),
        ("malformed", "invalid JSON"),
        ("timeout", "5-second"),
        ("oversized", "size limit"),
    ],
)
async def test_invalid_actions_are_reported_without_leaking_responses(stack, mode, message):
    stack.server.mode = mode
    report = await stack.tester.run(stack.owner.id, stack.bot_id)
    assert not report.passed
    assert all(check.passed for check in report.checks[:2])
    assert all(not check.passed and check.action is None for check in report.checks[2:])
    assert message in report.checks[2].message
    assert stack.server.token not in report.model_dump_json()
    assert "sensitive internal detail" not in report.model_dump_json()


@pytest.mark.parametrize("mode,failed_index", [("health_bad", 0), ("verify_bad", 1)])
async def test_health_and_verification_failures_are_reported(stack, mode, failed_index):
    stack.server.mode = mode
    report = await stack.tester.run(stack.owner.id, stack.bot_id)
    assert not report.passed
    assert not report.checks[failed_index].passed
    assert all(check.passed for check in report.checks[2:])


async def test_route_requires_session_origin_and_owned_bot(stack):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(stack.app), base_url="http://testserver"
    ) as client:
        path = f"/api/v1/bots/{stack.bot_id}/test"
        headers = {"Origin": "http://testserver"}
        assert (await client.post(path, headers=headers)).status_code == 401
        assert (await client.post(path)).status_code == 403
        outsider = await stack.platform.user("outsider@example.com")
        for account, expected in ((outsider, 404), (stack.owner, 200)):
            issued = await stack.platform.auth.login(account.email, "long-enough-password")
            client.cookies.set("poker_session", issued.token)
            response = await client.post(path, headers=headers)
            assert response.status_code == expected
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["passed"]
        assert stack.server.token not in response.text
        assert len(stack.server.requests) == 6


async def test_test_and_admission_are_exclusive_and_duplicates_rejected(stack):
    match_id = await prepare_match(stack)
    stack.server.mode = "blocked"
    running = asyncio.create_task(stack.tester.run(stack.owner.id, stack.bot_id))
    await asyncio.wait_for(stack.server.started.wait(), 1)
    with pytest.raises(BotTestBusyError):
        await stack.tester.run(stack.owner.id, stack.bot_id)
    start = asyncio.create_task(stack.platform.matches.start(stack.platform.admin, match_id))
    await asyncio.sleep(0)
    assert not start.done()
    stack.server.release.set()
    assert (await running).passed
    await start
    stack.server.requests.clear()
    with pytest.raises(MatchCommandError, match="live match"):
        await stack.tester.run(stack.owner.id, stack.bot_id)
    assert stack.server.requests == []


async def test_suite_timeout_releases_endpoint_and_capacity(stack, monkeypatch):
    monkeypatch.setattr("poker_bot_platform.integration.bot_testing.SUITE_TIMEOUT_SECONDS", 0.02)
    stack.server.mode = "blocked"
    with pytest.raises(TimeoutError):
        await stack.tester.run(stack.owner.id, stack.bot_id)
    stack.server.mode = "valid"
    assert (await stack.tester.run(stack.owner.id, stack.bot_id)).passed


async def test_owner_lookup_is_required_before_outbound_requests(stack):
    outsider = await stack.platform.user("outsider@example.com")
    with pytest.raises(AuthNotFoundError):
        await stack.tester.run(outsider.id, stack.bot_id)
    assert stack.server.requests == []


async def test_suite_timeout_is_safe_api_error(stack, monkeypatch):
    monkeypatch.setattr("poker_bot_platform.integration.bot_testing.SUITE_TIMEOUT_SECONDS", 0.02)
    stack.server.mode = "blocked"
    issued = await stack.platform.auth.login(stack.owner.email, "long-enough-password")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(stack.app),
        base_url="http://testserver",
        cookies={"poker_session": issued.token},
    ) as client:
        response = await client.post(
            f"/api/v1/bots/{stack.bot_id}/test", headers={"Origin": "http://testserver"}
        )
    assert response.status_code == 504
    assert stack.server.token not in response.text


async def test_global_capacity_is_bounded_and_released_on_cancellation(stack):
    pairs = [(stack.owner.id, stack.bot_id)]
    for index in (1, 2):
        owner = await stack.platform.user(f"bot-{index}@example.com")
        created = await stack.platform.bots.create(
            owner.id, f"Bot {index}", f"10.20.0.{20 + index}", 8001
        )
        pairs.append((owner.id, created.profile.id))
    stack.server.mode = "blocked"
    first = asyncio.create_task(stack.tester.run(*pairs[0]))
    await asyncio.wait_for(stack.server.started.wait(), 1)
    second = asyncio.create_task(stack.tester.run(*pairs[1]))
    await asyncio.sleep(0)
    try:
        with pytest.raises(BotTestBusyError):
            await stack.tester.run(*pairs[2])
    finally:
        first.cancel()
        second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
    stack.server.mode = "valid"
    assert (await stack.tester.run(*pairs[0])).passed


async def test_live_match_blocks_bot_mutations_without_changing_profile(stack):
    match_id = await prepare_match(stack)
    await stack.platform.matches.start(stack.platform.admin, match_id)
    before = await stack.platform.bots.get(stack.owner.id, stack.bot_id)
    issued = await stack.platform.auth.login(stack.owner.email, "long-enough-password")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(stack.app),
        base_url="http://testserver",
        cookies={"poker_session": issued.token},
        headers={"Origin": "http://testserver"},
    ) as client:
        path = f"/api/v1/bots/{stack.bot_id}"
        assert (await client.patch(path, json={"port": 9000})).status_code == 409
        assert (await client.post(path + "/rotate-token")).status_code == 409
        assert (await client.delete(path)).status_code == 409
    assert await stack.platform.bots.get(stack.owner.id, stack.bot_id) == before


async def test_lobby_change_during_readiness_does_not_admit_unchecked_bot(stack, monkeypatch):
    match_id = await prepare_match(stack)

    async def healthy(_profile):
        late = await stack.platform.user("late@example.com")
        coordinator = await stack.platform.registry.get(match_id)
        await stack.platform.join_human(late, coordinator.state.join_code, "Late")
        return True

    monkeypatch.setattr(stack.platform.matches, "_healthy", healthy)
    with pytest.raises(MatchCommandError, match="lobby changed"):
        await stack.platform.matches.start(stack.platform.admin, match_id)
    assert (await stack.platform.registry.get(match_id)).state.status.value == "lobby"


async def test_shared_endpoint_cannot_start_in_two_matches(stack):
    first = await prepare_match(stack)
    second, code = await stack.platform.create_match()
    await stack.platform.matches.join(stack.owner, code, EntryKind.BOT, None, stack.bot_id)
    human = await stack.platform.user("second@example.com")
    await stack.platform.join_human(human, code, "Other human")
    await stack.platform.matches.start(stack.platform.admin, first)
    with pytest.raises(MatchCommandError, match="live match"):
        await stack.platform.matches.start(stack.platform.admin, second)


async def test_multi_endpoint_reservations_release_partial_acquisitions_on_cancel(
    stack: TestStack,
) -> None:
    usage = stack.platform.matches.endpoints
    first, second = ("192.168.1.1", 8001), ("192.168.1.2", 8001)
    entered = asyncio.Event()
    async with usage.reserve([second]):

        async def waiting():
            entered.set()
            async with usage.reserve([second, first]):
                pytest.fail("second endpoint should still be locked")

        task = asyncio.create_task(waiting())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(1):
            async with usage.reserve([first]):
                pass
    async with usage.reserve([second, first]):
        pass


async def test_reversed_multi_endpoint_requests_do_not_deadlock(stack: TestStack) -> None:
    usage = stack.platform.matches.endpoints
    keys = [("192.168.1.20", 8001), ("192.168.1.21", 8001)]
    acquired, release, second_started = (asyncio.Event() for _ in range(3))

    async def first():
        async with usage.reserve(keys):
            acquired.set()
            await release.wait()

    async def second():
        second_started.set()
        async with usage.reserve(reversed(keys)):
            pass

    one = asyncio.create_task(first())
    await acquired.wait()
    two = asyncio.create_task(second())
    await second_started.wait()
    assert not two.done()
    release.set()
    await asyncio.wait_for(asyncio.gather(one, two), 1)


async def test_passive_strategy_does_not_need_to_raise(stack):
    original = stack.server.__call__

    async def passive(request):
        if request.url.path != "/v1/action":
            return await original(request)
        payload = BotActionRequest.model_validate_json(request.content)
        action = (
            "check"
            if any(item.action.value == "check" for item in payload.legal_actions)
            else "call"
        )
        return httpx.Response(
            200,
            json={
                "protocol": payload.protocol,
                "match_id": payload.match_id,
                "table_id": payload.table_id,
                "hand_id": payload.hand_id,
                "decision_id": payload.decision_id,
                "table_version": payload.table_version,
                "action": action,
            },
        )

    async with BotGateway(
        participant_subnet=ip_network("10.20.0.0/24"), transport=httpx.MockTransport(passive)
    ) as gateway:
        report = await BotTestingService(stack.platform.matches, gateway).run(
            stack.owner.id, stack.bot_id
        )
    assert report.passed
    assert [check.action.value for check in report.checks[2:]] == ["check", "call", "call", "call"]


async def test_admission_rechecks_endpoint_after_waiting_for_setup(stack):
    match_id = await prepare_match(stack)
    key = ("10.20.0.20", 8001)
    async with stack.platform.matches.endpoints.reserve([key]):
        start = asyncio.create_task(stack.platform.matches.start(stack.platform.admin, match_id))
        await asyncio.sleep(0)
        assert not start.done()
        await stack.platform.bots.update(stack.owner.id, stack.bot_id, port=9000)
    with pytest.raises(MatchCommandError, match="settings changed"):
        await start
    assert (await stack.platform.registry.get(match_id)).state.status.value == "lobby"
