from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

import httpx
import pytest

from poker_bot_platform.api.models import PlayerActionRequest
from poker_bot_platform.auth import AuthService, EntrantService, InMemoryAuthRepository
from poker_bot_platform.bots import BotGateway
from poker_bot_platform.bots.models import BotActionRequest, VerifyRequest
from poker_bot_platform.bots.reference import deterministic_reference_action
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.domain import ActionType, EntryKind, TournamentConfig
from poker_bot_platform.integration import (
    AdminCoordinatorService,
    GameplayConflictError,
    HeadlessGameplayRuntime,
    RuntimeAdminCoordinatorService,
    SyncedEntrantService,
    TournamentRegistry,
)
from poker_bot_platform.persistence import InMemoryTableRepository
from poker_bot_platform.tournament import InMemoryTournamentStore


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


@dataclass
class RuntimeStack:
    auth: AuthService
    entrants: SyncedEntrantService
    admin: RuntimeAdminCoordinatorService
    runtime: HeadlessGameplayRuntime
    accounts: InMemoryAuthRepository
    tables: InMemoryTableRepository
    tournament_store: InMemoryTournamentStore


def make_stack(
    transport: httpx.AsyncBaseTransport,
    *,
    clock: MutableClock | None = None,
) -> tuple[RuntimeStack, BotGateway]:
    accounts = InMemoryAuthRepository()
    tables = InMemoryTableRepository()
    tournament_store = InMemoryTournamentStore()
    registry = TournamentRegistry(tournament_store, tables)
    token_store = EncryptedTokenStore.from_deployment_secret("runtime-test-secret" * 3)
    gateway = BotGateway(
        participant_subnet=ip_network("192.168.1.0/24"),
        transport=transport,
        now=clock,
    )
    auth = AuthService(accounts, clock=clock)
    account_entrants = EntrantService(
        accounts,
        token_store=token_store,
        participant_subnet=ip_network("192.168.1.0/24"),
        verifier=gateway,
        clock=clock,
    )
    entrants = SyncedEntrantService(account_entrants, registry)
    runtime = HeadlessGameplayRuntime(
        registry,
        tables,
        accounts,
        token_store,
        gateway,
        clock=clock,
    )
    admin = RuntimeAdminCoordinatorService(
        AdminCoordinatorService(registry),
        runtime,
        registry,
    )
    return (
        RuntimeStack(
            auth,
            entrants,
            admin,
            runtime,
            accounts,
            tables,
            tournament_store,
        ),
        gateway,
    )


def bot_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/verify":
        payload = VerifyRequest.model_validate(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"protocol": "poker-bot.v1", "challenge": payload.challenge},
        )
    if request.url.path == "/v1/action":
        payload = BotActionRequest.model_validate(json.loads(request.content))
        response = deterministic_reference_action(payload)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=response.model_dump_json(),
        )
    raise AssertionError(f"unexpected bot route {request.url.path}")


@pytest.mark.asyncio
async def test_runtime_dispatches_real_hand_drives_bot_and_projects_private_state() -> None:
    bot_actions = 0

    def counting_handler(request: httpx.Request) -> httpx.Response:
        nonlocal bot_actions
        if request.url.path == "/v1/action":
            bot_actions += 1
        return bot_handler(request)

    stack, gateway = make_stack(httpx.MockTransport(counting_handler))
    async with gateway:
        await stack.admin.create_tournament("event", TournamentConfig(), "admin")
        await stack.admin.open_registration("event", "admin")
        human = await stack.auth.register("human@example.com", "long-enough-password")
        bot = await stack.auth.register("bot@example.com", "long-enough-password")
        human_entrant = await stack.entrants.register(
            human.id,
            "event",
            EntryKind.HUMAN,
            "Human",
        )
        await stack.entrants.register(bot.id, "event", EntryKind.BOT, "Bot")
        await stack.entrants.configure_bot(bot.id, "event", "192.168.1.50", 8_080)
        await stack.entrants.verify_bot(bot.id, "event")
        await stack.admin.seat("event", "admin")
        await stack.admin.start("event", "admin")

        state = await stack.runtime.player_state(human.id, "event")
        assert state.decision is not None
        own = next(seat for seat in state.seats if seat.entrant_id == human_entrant.id)
        opponents = [seat for seat in state.seats if seat.entrant_id != human_entrant.id]
        assert len(own.hole_cards) == 2
        assert all(seat.hole_cards == () for seat in opponents)
        serialized = state.model_dump_json()
        assert "deck_order" not in serialized
        assert "engine_state" not in serialized

        with pytest.raises(GameplayConflictError, match="stale"):
            await stack.runtime.submit_human_action(
                human.id,
                "event",
                PlayerActionRequest(
                    decision_id="stale-decision",
                    table_version=state.decision.table_version,
                    action=ActionType.FOLD,
                ),
            )

        next_state = state
        for _ in range(20):
            assert next_state.decision is not None
            legal = {item.action: item for item in next_state.decision.legal_actions}
            action = ActionType.FOLD if ActionType.FOLD in legal else ActionType.CHECK
            next_state = await stack.runtime.submit_human_action(
                human.id,
                "event",
                PlayerActionRequest(
                    decision_id=next_state.decision.decision_id,
                    table_version=next_state.decision.table_version,
                    action=action,
                ),
            )
            if next_state.hand_id != state.hand_id:
                break

    assert next_state.hand_number >= 2
    assert next_state.hand_id != state.hand_id
    assert bot_actions >= 1


@pytest.mark.asyncio
async def test_runtime_expires_human_decision_and_restart_falls_back_once() -> None:
    clock = MutableClock(datetime(2026, 10, 1, 18, 0, tzinfo=UTC))
    transport = httpx.MockTransport(bot_handler)
    stack, gateway = make_stack(transport, clock=clock)
    async with gateway:
        await stack.admin.create_tournament("event", TournamentConfig(), "admin")
        await stack.admin.open_registration("event", "admin")
        first = await stack.auth.register("one@example.com", "long-enough-password")
        second = await stack.auth.register("two@example.com", "long-enough-password")
        await stack.entrants.register(first.id, "event", EntryKind.HUMAN, "One")
        await stack.entrants.register(second.id, "event", EntryKind.HUMAN, "Two")
        await stack.admin.seat("event", "admin")
        await stack.admin.start("event", "admin")

        first_state = await stack.runtime.player_state(first.id, "event")
        second_state = await stack.runtime.player_state(second.id, "event")
        actor = first if first_state.decision is not None else second
        original = first_state if first_state.decision is not None else second_state
        assert original.decision is not None

        # A new runtime represents a process restart. Restoring the table sees the
        # unresolved durable decision, applies exactly one restart fallback, and
        # reconciles the completed hand into the tournament state.
        restored_registry = TournamentRegistry(stack.tournament_store, stack.tables)
        restored_runtime = HeadlessGameplayRuntime(
            restored_registry,
            stack.tables,
            stack.accounts,
            EncryptedTokenStore.from_deployment_secret("runtime-test-secret" * 3),
            gateway,
            clock=clock,
        )
        after_restart = await restored_runtime.player_state(actor.id, "event")
        assert after_restart.hand_id != original.hand_id

        other = second if actor.id == first.id else first
        other_state = await restored_runtime.player_state(other.id, "event")
        timeout_actor = actor if after_restart.decision is not None else other
        timeout_state = after_restart if after_restart.decision is not None else other_state
        assert timeout_state.decision is not None
        clock.advance(31)
        after_timeout = await restored_runtime.player_state(timeout_actor.id, "event")
        assert after_timeout.decision is None or (
            after_timeout.decision.decision_id != timeout_state.decision.decision_id
        )
