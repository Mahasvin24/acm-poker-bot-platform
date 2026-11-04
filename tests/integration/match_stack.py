from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

import httpx

from poker_bot_platform.auth import (
    Account,
    AuthService,
    BotProfileService,
    InMemoryAuthRepository,
    bootstrap_admin,
)
from poker_bot_platform.bots import BotActionRequest, BotGateway
from poker_bot_platform.bots.reference import deterministic_reference_action
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.domain import EntryKind, MatchConfig
from poker_bot_platform.integration import MatchRuntime, MatchService, PacingConfig
from poker_bot_platform.match import InMemoryMatchStore, MatchRegistry
from poker_bot_platform.persistence import InMemoryTableRepository

SUBNET = ip_network("10.20.0.0/24")


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 18, 19, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


@dataclass
class FakeBotNetwork:
    """In-process bot hosts addressed by IP; behaviour can be changed per host."""

    tokens: dict[str, str] = field(default_factory=dict)
    broken: set[str] = field(default_factory=set)
    delay_seconds: float = 0.0
    calls: Counter[tuple[str, str]] = field(default_factory=Counter)
    action_requests: list[dict[str, object]] = field(default_factory=list)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.calls[(host, request.url.path)] += 1
        if host in self.broken:
            return httpx.Response(500, json={"detail": "crashed"})
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"protocol": "poker-bot.v2", "status": "ready"})
        if request.headers.get("authorization") != f"Bearer {self.tokens.get(host)}":
            return httpx.Response(401, json={"detail": "bad token"})
        if request.url.path == "/v1/verify":
            body = json.loads(request.content)
            return httpx.Response(
                200, json={"protocol": "poker-bot.v2", "challenge": body["challenge"]}
            )
        self.action_requests.append(json.loads(request.content))
        bot_request = BotActionRequest.model_validate_json(request.content)
        action = deterministic_reference_action(bot_request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=action.model_dump_json(exclude_none=True),
        )


@dataclass
class MatchStack:
    clock: MutableClock
    auth_repository: InMemoryAuthRepository
    auth: AuthService
    bots: BotProfileService
    gateway: BotGateway
    network: FakeBotNetwork
    registry: MatchRegistry
    tables: InMemoryTableRepository
    runtime: MatchRuntime
    matches: MatchService
    admin: Account

    async def user(self, email: str) -> Account:
        return await self.auth.register(email, "long-enough-password")

    async def verified_bot(self, owner: Account, name: str, host: str) -> str:
        created = await self.bots.create(owner.id, name, host, 8001)
        self.network.tokens[host] = created.bearer_token
        await self.bots.verify(owner.id, created.profile.id)
        return created.profile.id

    async def create_match(self, config: MatchConfig | None = None) -> tuple[str, str]:
        view = await self.matches.create(self.admin, "Club Night", config or MatchConfig())
        assert view.join_code is not None
        return view.match_id, view.join_code

    async def join_human(self, account: Account, code: str, name: str) -> None:
        await self.matches.join(account, code, EntryKind.HUMAN, name, None)

    async def join_bot(self, account: Account, code: str, profile_id: str) -> None:
        await self.matches.join(account, code, EntryKind.BOT, None, profile_id)

    async def drive(self, match_id: str) -> None:
        await self.runtime.drive(match_id)


async def build_stack(pacing: PacingConfig | None = None) -> MatchStack:
    clock = MutableClock()
    auth_repository = InMemoryAuthRepository()
    auth = AuthService(auth_repository, clock=clock)
    network = FakeBotNetwork()
    gateway = BotGateway(
        participant_subnet=SUBNET,
        transport=httpx.MockTransport(network.handle),
        now=clock,
    )
    token_store = EncryptedTokenStore.from_deployment_secret("3f9c1a7e5b2d8046c9e1f7a3b5d20e84")
    bots = BotProfileService(
        auth_repository,
        token_store=token_store,
        participant_subnet=SUBNET,
        verifier=gateway,
        clock=clock,
    )
    registry = MatchRegistry(InMemoryMatchStore(), clock=clock)
    tables = InMemoryTableRepository()
    runtime = MatchRuntime(
        registry,
        tables,
        auth_repository,
        token_store,
        gateway,
        clock=clock,
        pacing=pacing,
    )
    matches = MatchService(registry, auth_repository, bots, gateway, runtime, clock=clock)
    admin = await bootstrap_admin(auth_repository, "admin@example.com", "admin-long-password")
    return MatchStack(
        clock=clock,
        auth_repository=auth_repository,
        auth=auth,
        bots=bots,
        gateway=gateway,
        network=network,
        registry=registry,
        tables=tables,
        runtime=runtime,
        matches=matches,
        admin=admin,
    )
