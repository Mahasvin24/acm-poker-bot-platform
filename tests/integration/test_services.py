from __future__ import annotations

import asyncio
from ipaddress import ip_network

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from poker_bot_platform.api.router import create_api_router
from poker_bot_platform.app import create_app
from poker_bot_platform.auth.repository import (
    AuthConflictError,
    AuthRepositoryError,
    InMemoryAuthRepository,
)
from poker_bot_platform.auth.service import AuthService, EntrantService
from poker_bot_platform.bots import VerificationOutcome
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.config import Settings
from poker_bot_platform.domain import EntryKind, TournamentConfig, TournamentStatus
from poker_bot_platform.integration import (
    AdminCoordinatorService,
    SyncedEntrantService,
    TournamentRegistry,
)
from poker_bot_platform.persistence import InMemoryTableRepository
from poker_bot_platform.tournament import InMemoryTournamentStore, TournamentError


class SuccessfulVerifier:
    async def verify(self, *_args: object) -> VerificationOutcome:
        return VerificationOutcome(verified=True)


def service_stack() -> tuple[
    AuthService,
    SyncedEntrantService,
    AdminCoordinatorService,
    TournamentRegistry,
]:
    auth_repository = InMemoryAuthRepository()
    auth = AuthService(auth_repository)
    registry = TournamentRegistry(
        InMemoryTournamentStore(), InMemoryTableRepository(), accounts=auth_repository
    )
    accounts = EntrantService(
        auth_repository,
        token_store=EncryptedTokenStore.from_deployment_secret("x" * 32),
        participant_subnet=ip_network("192.168.1.0/24"),
        verifier=SuccessfulVerifier(),
    )
    return (
        auth,
        SyncedEntrantService(accounts, registry),
        AdminCoordinatorService(registry),
        registry,
    )


@pytest.mark.asyncio
async def test_account_entrant_is_visible_to_tournament_seating() -> None:
    auth, entrants, admin, registry = service_stack()
    await admin.create_tournament("club-event", TournamentConfig(), "admin")
    await admin.open_registration("club-event", "admin")
    first = await auth.register("one@example.com", "long-enough-password")
    second = await auth.register("two@example.com", "another-long-password")

    await entrants.register(first.id, "club-event", EntryKind.HUMAN, "One")
    await entrants.register(second.id, "club-event", EntryKind.HUMAN, "Two")
    result = await admin.seat("club-event", "admin")
    state = await admin.get_state("club-event")

    coordinator = await registry.get("club-event")
    assert result.status == TournamentStatus.SEATED.value
    assert state.entrant_count == 2
    assert state.human_count == 2
    assert state.table_count == 1
    assert {
        player.account_id for table in coordinator.state.tables for player in table.players
    } == {
        first.id,
        second.id,
    }


@pytest.mark.asyncio
async def test_bot_verification_propagates_and_closed_registration_is_rejected() -> None:
    auth, entrants, admin, registry = service_stack()
    await admin.create_tournament("club-event", TournamentConfig(), "admin")
    account = await auth.register("bot@example.com", "long-enough-password")

    with pytest.raises(AuthConflictError, match="not open"):
        await entrants.register(account.id, "club-event", EntryKind.BOT, "Bot")

    await admin.open_registration("club-event", "admin")
    registered = await entrants.register(account.id, "club-event", EntryKind.BOT, "Bot")
    await entrants.configure_bot(account.id, "club-event", "192.168.1.50", 8_080)
    await entrants.verify_bot(account.id, "club-event")

    coordinator = await registry.get("club-event")
    tournament_entrant = next(
        item for item in coordinator.state.entrants if item.entrant_id == registered.id
    )
    assert tournament_entrant.bot_verified


@pytest.mark.asyncio
@pytest.mark.parametrize("ip,port", [("192.168.1.51", 8_081), ("192.168.1.50", 8_080)])
async def test_replacing_verified_bot_endpoint_requires_reverification_before_seating(
    ip: str, port: int
) -> None:
    auth, entrants, admin, registry = service_stack()
    await admin.create_tournament("club-event", TournamentConfig(), "admin")
    await admin.open_registration("club-event", "admin")
    human = await auth.register("human@example.com", "long-enough-password")
    bot = await auth.register("bot@example.com", "long-enough-password")
    await entrants.register(human.id, "club-event", EntryKind.HUMAN, "Human")
    registered = await entrants.register(bot.id, "club-event", EntryKind.BOT, "Bot")
    original = await entrants.configure_bot(bot.id, "club-event", "192.168.1.50", 8_080)
    verified = await entrants.verify_bot(bot.id, "club-event")
    coordinator = await registry.get("club-event")
    assert verified.bot_verified_at is not None
    assert next(
        item for item in coordinator.state.entrants if item.entrant_id == registered.id
    ).bot_verified

    replacement = await entrants.configure_bot(bot.id, "club-event", ip, port)
    assert replacement.bearer_token != original.bearer_token
    assert replacement.entrant.bot_verified_at is None
    with pytest.raises(TournamentError, match="all bots must be verified"):
        await coordinator.seat_entrants(actor_id="admin")
    assert coordinator.state.status is TournamentStatus.REGISTRATION_OPEN
    assert coordinator.state.tables == ()
    assert not next(
        item for item in coordinator.state.entrants if item.entrant_id == registered.id
    ).bot_verified

    await entrants.verify_bot(bot.id, "club-event")
    result = await admin.seat("club-event", "admin")
    assert result.status == TournamentStatus.SEATED.value


def test_application_factory_mounts_headless_api_without_connecting_to_database() -> None:
    application = create_app(
        Settings(
            database_url="postgresql+asyncpg://unused:unused@localhost:5432/unused",
            secret_key="x" * 32,
            participant_subnet="192.168.1.0/24",
        )
    )
    with TestClient(application) as client:
        assert application.state.gameplay_scheduler.running
        response = client.get("/health")
    assert not application.state.gameplay_scheduler.running
    assert response.status_code == 200
    paths = set(application.openapi()["paths"])
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/admin/tournaments" in paths
    assert "/api/v1/tournaments/{tournament_id}/table" in paths
    assert "/api/v1/tournaments/{tournament_id}/table/action" in paths


async def verified_stack():
    auth, entrants, admin, registry = service_stack()
    await admin.create_tournament("event", TournamentConfig(), "admin")
    await admin.open_registration("event", "admin")
    bot = await auth.register("bot@race.test", "long-enough-password")
    human = await auth.register("human@race.test", "long-enough-password")
    await entrants.register(bot.id, "event", EntryKind.BOT, "Bot")
    await entrants.register(human.id, "event", EntryKind.HUMAN, "Human")
    await entrants.configure_bot(bot.id, "event", "192.168.1.50", 8080)
    await entrants.verify_bot(bot.id, "event")
    return entrants, admin, registry, bot


@pytest.mark.parametrize("operation", ["rotation_first", "verification_first"])
async def test_rotation_verification_and_seating_are_serialized(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrants, admin, registry, bot = await verified_stack()
    entered, release, second_entered, seating_entered = (asyncio.Event() for _ in range(4))
    name = "configure_bot" if operation == "rotation_first" else "verify_bot"
    original = getattr(entrants.accounts, name)

    async def paused(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(entrants.accounts, name, paused)

    async def rotate():
        return await entrants.configure_bot(bot.id, "event", "192.168.1.51", 8081)

    async def verify():
        return await entrants.verify_bot(bot.id, "event")

    first = asyncio.create_task(rotate() if operation == "rotation_first" else verify())
    await entered.wait()

    async def second_operation():
        second_entered.set()
        return await (verify() if operation == "rotation_first" else rotate())

    second = asyncio.create_task(second_operation())
    await second_entered.wait()
    assert not second.done()
    coordinator = await registry.get("event")

    async def seat():
        seating_entered.set()
        return await coordinator.seat_entrants(actor_id="admin")

    seating = asyncio.create_task(seat())
    await seating_entered.wait()
    assert not seating.done()
    release.set()
    await first
    await second
    current = await entrants.current(bot.id, "event")
    domain = next(item for item in coordinator.state.entrants if item.account_id == bot.id)
    assert (current.bot_verified_at is not None) == domain.bot_verified
    if operation == "rotation_first":
        assert current.bot_verified_at is not None
        assert (await seating).status is TournamentStatus.SEATED
    else:
        assert current.bot_verified_at is None
        with pytest.raises(TournamentError, match="verified"):
            await seating


@pytest.mark.parametrize("failure", ["invalid", "before_commit", "after_commit"])
async def test_failed_rotation_preserves_only_provably_valid_verification(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrants, admin, registry, bot = await verified_stack()
    before = await entrants.current(bot.id, "event")
    original = entrants.accounts.repository.configure_bot

    async def fail(*args):
        if failure == "after_commit":
            await original(*args)
        raise AuthRepositoryError("injected write failure")

    monkeypatch.setattr(entrants.accounts.repository, "configure_bot", fail)
    with pytest.raises(ValueError if failure == "invalid" else AuthRepositoryError):
        await entrants.configure_bot(
            bot.id, "event", "localhost" if failure == "invalid" else "192.168.1.51", 8081
        )
    after = await entrants.current(bot.id, "event")
    coordinator = await registry.get("event")
    domain = next(item for item in coordinator.state.entrants if item.account_id == bot.id)
    if failure == "after_commit":
        assert after.bot_verified_at is None
        assert not domain.bot_verified
        with pytest.raises(TournamentError, match="verified"):
            await coordinator.seat_entrants(actor_id="admin")
    else:
        assert after == before
        assert domain.bot_verified
        assert (await admin.seat("event", "admin")).status == "seated"


async def test_stale_credential_verification_is_rejected_by_repository() -> None:
    entrants, _, registry, bot = await verified_stack()
    old = await entrants.current(bot.id, "event")
    await entrants.configure_bot(bot.id, "event", "192.168.1.51", 8081)
    from datetime import UTC, datetime

    with pytest.raises(AuthConflictError, match="changed"):
        await entrants.accounts.repository.mark_bot_verified(
            old.id, old.bot_token_ciphertext, datetime.now(UTC)
        )
    assert (await entrants.current(bot.id, "event")).bot_verified_at is None
    assert not (await registry.get("event")).state.entrants[0].bot_verified


async def test_late_network_verification_cannot_validate_rotated_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrants, _, registry, bot = await verified_stack()
    entered, release = asyncio.Event(), asyncio.Event()

    class DelayedVerifier:
        async def verify(self, *_args):
            entered.set()
            await release.wait()
            return VerificationOutcome(verified=True)

    monkeypatch.setattr(entrants.accounts, "verifier", DelayedVerifier())
    # Exercise the repository's defense as well as the application-level lock:
    # an already-issued low-level request still must fail its credential CAS.
    pending = asyncio.create_task(entrants.accounts.verify_bot(bot.id, "event"))
    await entered.wait()
    await entrants.configure_bot(bot.id, "event", "192.168.1.51", 8081)
    release.set()
    with pytest.raises(AuthConflictError, match="changed"):
        await pending
    assert (await entrants.accounts.current(bot.id, "event")).bot_verified_at is None
    assert not (await registry.get("event")).state.entrants[0].bot_verified


async def test_cancelled_rotation_restores_unchanged_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrants, _, registry, bot = await verified_stack()
    before = await entrants.current(bot.id, "event")
    entered = asyncio.Event()

    async def paused(*_args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(entrants.accounts.repository, "configure_bot", paused)
    pending = asyncio.create_task(entrants.configure_bot(bot.id, "event", "192.168.1.51", 8081))
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert await entrants.current(bot.id, "event") == before
    assert (await registry.get("event")).state.entrants[0].bot_verified


async def test_entry_status_does_not_claim_verification_when_tournament_invalidated() -> None:
    entrants, _, registry, bot = await verified_stack()
    entrant = await entrants.current(bot.id, "event")
    coordinator = await registry.get("event")
    await coordinator.invalidate_bot_verification(entrant.id, actor_id=bot.id)
    assert (await entrants.accounts.current(bot.id, "event")).bot_verified_at is not None
    assert (await entrants.current(bot.id, "event")).bot_verified_at is None


async def test_entry_readiness_metadata_is_owner_only_and_tracks_actual_tournament_status() -> None:
    entrants, admin, registry, bot = await verified_stack()
    auth = AuthService(entrants.accounts.repository)
    calls = []

    async def status_lookup(tournament_id: str):
        calls.append(tournament_id)
        return await entrants.tournament_status(tournament_id)

    app = FastAPI()
    app.include_router(
        create_api_router(
            auth=auth,
            entrants=entrants,
            admin=admin,
            tournament_status=status_lookup,
            allowed_origin="http://testserver",
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as client:
        path = "/api/v1/tournaments/event/entrant"
        assert (await client.get(path)).status_code == 401
        assert not calls
        outsider = await auth.register("outside@readiness.test", "long-enough-password")
        session = await auth.login(outsider.email, "long-enough-password")
        client.cookies.set("poker_session", session.token)
        assert (await client.get(path)).status_code == 404
        assert not calls
        session = await auth.login(bot.email, "long-enough-password")
        client.cookies.set("poker_session", session.token)
        response = await client.get(path)
        assert response.json()["tournament_status"] == "registration_open"
        assert response.json()["bot_verified_at"] is not None
        assert "bot_token_ciphertext" not in response.text
        await admin.seat("event", "admin")  # No action-test report is required for eligibility.
        assert (await client.get(path)).json()["tournament_status"] == "seated"
        await (await registry.get("event")).start(actor_id="admin")
        assert (await client.get(path)).json()["tournament_status"] == "running"
