from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from ipaddress import ip_network
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from poker_bot_platform.api.router import create_api_router
from poker_bot_platform.auth import AuthService, EntrantService, InMemoryAuthRepository
from poker_bot_platform.auth.models import Account
from poker_bot_platform.auth.repository import AuthConflictError
from poker_bot_platform.bots import BotGateway
from poker_bot_platform.bots.models import BotActionRequest
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.domain import EntryKind, TournamentConfig
from poker_bot_platform.integration import (
    AdminCoordinatorService,
    GameplayScheduler,
    HeadlessGameplayRuntime,
    SyncedEntrantService,
    TournamentRegistry,
)
from poker_bot_platform.integration.bot_testing import BotTestBusyError, BotTestingService
from poker_bot_platform.persistence import InMemoryTableRepository
from poker_bot_platform.tournament import InMemoryTournamentStore, TournamentError


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
                    "protocol": "poker-bot.v1",
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
            "protocol": "poker-bot.v1",
            "tournament_id": payload.tournament_id,
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
    auth: AuthService
    entrants: SyncedEntrantService
    registry: TournamentRegistry
    tester: BotTestingService
    owner: Account
    server: BotServer
    app: FastAPI


@pytest.fixture
async def stack() -> AsyncIterator[TestStack]:
    server = BotServer()
    repository = InMemoryAuthRepository()
    auth = AuthService(repository)
    registry = TournamentRegistry(
        InMemoryTournamentStore(), InMemoryTableRepository(), accounts=repository
    )
    async with BotGateway(
        participant_subnet=ip_network("192.168.1.0/24"), transport=httpx.MockTransport(server)
    ) as gateway:
        accounts = EntrantService(
            repository,
            token_store=EncryptedTokenStore.from_deployment_secret("x" * 32),
            participant_subnet=ip_network("192.168.1.0/24"),
            verifier=gateway,
        )
        entrants = SyncedEntrantService(accounts, registry)
        admin = AdminCoordinatorService(registry)
        await admin.create_tournament("event", TournamentConfig(), "admin")
        await admin.open_registration("event", "admin")
        owner = await auth.register("bot@example.com", "long-enough-password")
        await entrants.register(owner.id, "event", EntryKind.BOT, "Test Bot")
        registration = await entrants.configure_bot(owner.id, "event", "192.168.1.20", 8001)
        server.token = registration.bearer_token
        tester = BotTestingService(accounts, registry, gateway)
        app = FastAPI()
        app.include_router(
            create_api_router(
                auth=auth,
                entrants=entrants,
                admin=admin,
                bot_testing=tester,
                allowed_origin="http://testserver",
            )
        )
        yield TestStack(auth, entrants, registry, tester, owner, server, app)


async def test_successful_suite_is_bounded_private_and_does_not_verify_or_change_state(
    stack: TestStack,
) -> None:
    tournament = await stack.registry.get("event")
    before = tournament.state
    entry = await stack.entrants.current(stack.owner.id, "event")
    report = await stack.tester.run(stack.owner.id, "event")
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
    assert all(item.elapsed_ms >= 0 for item in report.checks)
    assert tournament.state == before
    assert await stack.entrants.current(stack.owner.id, "event") == entry
    serialized = report.model_dump_json()
    assert stack.server.token not in serialized
    assert entry.bot_token_ciphertext not in serialized
    assert all(len(request.content) < 64 * 1024 for request in stack.server.requests)


@pytest.mark.parametrize(
    "mode,message",
    [
        ("raise_low", "out of bounds"),
        ("raise_high", "out of bounds"),
        ("stale", "identifiers"),
        ("malformed", "invalid JSON"),
        ("timeout", "3-second"),
        ("oversized", "size limit"),
    ],
)
async def test_invalid_actions_are_reported_without_leaking_responses(
    stack: TestStack, mode: str, message: str
) -> None:
    stack.server.mode = mode
    report = await stack.tester.run(stack.owner.id, "event")
    assert not report.passed
    assert all(check.passed for check in report.checks[:2])
    assert all(not check.passed and check.action is None for check in report.checks[2:])
    assert message in report.checks[2].message
    assert stack.server.token not in report.model_dump_json()
    assert "sensitive internal detail" not in report.model_dump_json()


async def test_test_route_requires_session_origin_and_owned_configured_bot(
    stack: TestStack,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(stack.app), base_url="http://testserver"
    ) as client:
        path = "/api/v1/tournaments/event/entrant/bot-endpoint/test"
        headers = {"Origin": "http://testserver"}
        assert (await client.post(path, headers=headers)).status_code == 401
        assert (await client.post(path)).status_code == 403
        outsider = await stack.auth.register("outsider@example.com", "long-enough-password")
        human = await stack.auth.register("human@example.com", "long-enough-password")
        unconfigured = await stack.auth.register("empty@example.com", "long-enough-password")
        await stack.entrants.register(human.id, "event", EntryKind.HUMAN, "Human")
        await stack.entrants.register(unconfigured.id, "event", EntryKind.BOT, "Empty")
        for account, expected in [
            (outsider, 404),
            (human, 409),
            (unconfigured, 409),
            (stack.owner, 200),
        ]:
            issued = await stack.auth.login(account.email, "long-enough-password")
            client.cookies.set("poker_session", issued.token)
            response = await client.post(path, headers=headers)
            assert response.status_code == expected
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["passed"]
        assert stack.server.token not in response.text
        assert len(stack.server.requests) == 6


async def test_seating_waits_and_duplicate_runs_are_rejected(stack: TestStack) -> None:
    stack.server.mode = "blocked"
    running = asyncio.create_task(stack.tester.run(stack.owner.id, "event"))
    await asyncio.wait_for(stack.server.started.wait(), 1)
    with pytest.raises(BotTestBusyError):
        await stack.tester.run(stack.owner.id, "event")
    tournament = await stack.registry.get("event")
    seating = asyncio.create_task(tournament.seat_entrants(actor_id="admin"))
    await asyncio.sleep(0)
    assert not seating.done()
    stack.server.release.set()
    assert (await running).passed
    with pytest.raises(TournamentError):
        await seating  # Fixture has only one unverified entrant; normal seating rules still apply.


async def test_suite_timeout_releases_capacity_and_registration_lock(
    stack: TestStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("poker_bot_platform.integration.bot_testing.SUITE_TIMEOUT_SECONDS", 0.02)
    stack.server.mode = "blocked"
    with pytest.raises(TimeoutError):
        await stack.tester.run(stack.owner.id, "event")
    stack.server.mode = "valid"
    assert (await stack.tester.run(stack.owner.id, "event")).passed


async def test_closed_registration_rejects_test_without_outbound_calls(stack: TestStack) -> None:
    await stack.entrants.verify_bot(stack.owner.id, "event")
    human = await stack.auth.register("human@example.com", "long-enough-password")
    await stack.entrants.register(human.id, "event", EntryKind.HUMAN, "Human")
    tournament = await stack.registry.get("event")
    await tournament.seat_entrants(actor_id="admin")
    stack.server.requests.clear()
    with pytest.raises(AuthConflictError):
        await stack.tester.run(stack.owner.id, "event")
    assert stack.server.requests == []


@pytest.mark.parametrize("mode,failed_index", [("health_bad", 0), ("verify_bad", 1)])
async def test_health_and_verification_failures_are_reported(
    stack: TestStack, mode: str, failed_index: int
) -> None:
    stack.server.mode = mode
    report = await stack.tester.run(stack.owner.id, "event")
    assert not report.passed
    assert len(report.checks) == 6
    assert not report.checks[failed_index].passed
    assert all(check.passed for check in report.checks[2:])


async def test_endpoint_used_by_another_running_tournament_is_not_called(stack: TestStack) -> None:
    admin = AdminCoordinatorService(stack.registry)
    await admin.create_tournament("other", TournamentConfig(), "admin")
    await admin.open_registration("other", "admin")
    await stack.entrants.register(stack.owner.id, "other", EntryKind.BOT, "Same Bot")
    configured = await stack.entrants.configure_bot(stack.owner.id, "other", "192.168.1.20", 8001)
    stack.server.token = configured.bearer_token
    await stack.entrants.verify_bot(stack.owner.id, "other")
    human = await stack.auth.register("human@example.com", "long-enough-password")
    await stack.entrants.register(human.id, "other", EntryKind.HUMAN, "Human")
    other = await stack.registry.get("other")
    await other.seat_entrants(actor_id="admin")
    await other.start(actor_id="admin")
    stack.server.requests.clear()
    before = other.state
    with pytest.raises(AuthConflictError, match="another live tournament"):
        await stack.tester.run(stack.owner.id, "event")
    assert other.state == before
    assert stack.server.requests == []


async def test_registration_check_does_not_block_shared_scheduler(stack: TestStack) -> None:
    gameplay = AsyncMock(spec=HeadlessGameplayRuntime)
    scheduler = GameplayScheduler(stack.registry, gameplay)
    await scheduler.run_once(now=0)
    stack.server.mode = "blocked"
    running = asyncio.create_task(stack.tester.run(stack.owner.id, "event"))
    await asyncio.wait_for(stack.server.started.wait(), 1)
    try:
        await asyncio.wait_for(scheduler.run_once(now=2), 0.5)
        gameplay.synchronize.assert_any_await("event")
    finally:
        stack.server.release.set()
        await running


async def test_check_and_call_strategy_is_not_required_to_raise(stack: TestStack) -> None:
    original = stack.server.__call__

    async def passive(request: httpx.Request) -> httpx.Response:
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
                "protocol": "poker-bot.v1",
                "tournament_id": payload.tournament_id,
                "table_id": payload.table_id,
                "hand_id": payload.hand_id,
                "decision_id": payload.decision_id,
                "table_version": payload.table_version,
                "action": action,
            },
        )

    async with BotGateway(
        participant_subnet=ip_network("192.168.1.0/24"), transport=httpx.MockTransport(passive)
    ) as gateway:
        # Use the same owned endpoint and account configuration with another transport.
        tester = BotTestingService(stack.entrants.accounts, stack.registry, gateway)
        report = await tester.run(stack.owner.id, "event")
    assert report.passed
    assert [item.action.value for item in report.checks[2:] if item.action] == [
        "check",
        "call",
        "call",
        "call",
    ]


async def test_global_capacity_is_bounded_and_released_on_cancellation(stack: TestStack) -> None:
    owners = [stack.owner]
    for index in [1, 2]:
        owner = await stack.auth.register(f"bot-{index}@example.com", "long-enough-password")
        await stack.entrants.register(owner.id, "event", EntryKind.BOT, f"Bot {index}")
        await stack.entrants.configure_bot(owner.id, "event", f"192.168.1.{20 + index}", 8001)
        owners.append(owner)
    stack.server.mode = "blocked"
    first = asyncio.create_task(stack.tester.run(owners[0].id, "event"))
    await asyncio.wait_for(stack.server.started.wait(), 1)
    second = asyncio.create_task(stack.tester.run(owners[1].id, "event"))
    await asyncio.sleep(0)  # Second reservation waits on this tournament's registration guard.
    try:
        with pytest.raises(BotTestBusyError):
            await stack.tester.run(owners[2].id, "event")
    finally:
        first.cancel()
        second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
    stack.server.mode = "valid"
    assert (await stack.tester.run(stack.owner.id, "event")).passed


async def test_suite_timeout_is_a_safe_api_error(
    stack: TestStack, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("poker_bot_platform.integration.bot_testing.SUITE_TIMEOUT_SECONDS", 0.02)
    stack.server.mode = "blocked"
    issued = await stack.auth.login(stack.owner.email, "long-enough-password")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(stack.app),
        base_url="http://testserver",
        cookies={"poker_session": issued.token},
    ) as client:
        response = await client.post(
            "/api/v1/tournaments/event/entrant/bot-endpoint/test",
            headers={"Origin": "http://testserver"},
        )
    assert response.status_code == 504
    assert response.json() == {"detail": "Bot test suite exceeded its 20-second limit."}
    assert stack.server.token not in response.text


async def other_tournament(stack: TestStack, name: str, ip: str = "192.168.1.20"):
    admin = AdminCoordinatorService(stack.registry)
    await admin.create_tournament(name, TournamentConfig(), "admin")
    await admin.open_registration(name, "admin")
    await stack.entrants.register(stack.owner.id, name, EntryKind.BOT, "Bot")
    original_token = stack.server.token
    configured = await stack.entrants.configure_bot(stack.owner.id, name, ip, 8001)
    stack.server.token = configured.bearer_token
    await stack.entrants.verify_bot(stack.owner.id, name)
    stack.server.token = original_token
    human = await stack.auth.register(f"{name}@race.test", "long-enough-password")
    await stack.entrants.register(human.id, name, EntryKind.HUMAN, "Human")
    return await stack.registry.get(name)


@pytest.mark.parametrize("testing_first", [True, False])
async def test_cross_tournament_endpoint_admission_is_exclusive(
    stack: TestStack, testing_first: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = await other_tournament(stack, "other")
    unrelated = await other_tournament(stack, "unrelated", "192.168.1.21")
    stack.server.requests.clear()
    stack.server.started.clear()
    if not testing_first:
        await other.seat_entrants(actor_id="admin")
        await other.start(actor_id="admin")
        with pytest.raises(AuthConflictError, match="another live tournament"):
            await stack.tester.run(stack.owner.id, "event")
        assert not stack.server.requests
        return

    outbound_states = []
    original = type(stack.server).__call__

    async def observed(self, request):
        outbound_states.append(other.state.status.value)
        return await original(self, request)

    monkeypatch.setattr(type(stack.server), "__call__", observed)
    stack.server.mode = "blocked"
    running = asyncio.create_task(stack.tester.run(stack.owner.id, "event"))
    await stack.server.started.wait()
    admission_entered = asyncio.Event()

    async def admit():
        admission_entered.set()
        await other.seat_entrants(actor_id="admin")
        await other.start(actor_id="admin")

    admission = asyncio.create_task(admit())
    await admission_entered.wait()
    assert not admission.done()
    # An unrelated endpoint must remain usable during this entire run.
    await asyncio.wait_for(unrelated.seat_entrants(actor_id="admin"), 1)
    await asyncio.wait_for(unrelated.start(actor_id="admin"), 1)
    stack.server.release.set()
    assert (await running).passed
    await admission
    assert "running" not in outbound_states
    assert other.state.status.value == "running"


async def test_multi_endpoint_reservations_release_partial_acquisitions_on_cancel(
    stack: TestStack,
) -> None:
    usage = stack.registry.endpoints
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
    usage = stack.registry.endpoints
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
