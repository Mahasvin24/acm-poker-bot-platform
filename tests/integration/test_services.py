from __future__ import annotations

from ipaddress import ip_network

import pytest
from fastapi.testclient import TestClient

from poker_bot_platform.app import create_app
from poker_bot_platform.auth.repository import AuthConflictError, InMemoryAuthRepository
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
from poker_bot_platform.tournament import InMemoryTournamentStore


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
    registry = TournamentRegistry(InMemoryTournamentStore(), InMemoryTableRepository())
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

    coordinator = await registry.get("club-event")
    assert result.status == TournamentStatus.SEATED.value
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


def test_application_factory_mounts_headless_api_without_connecting_to_database() -> None:
    application = create_app(
        Settings(
            database_url="postgresql+asyncpg://unused:unused@localhost:5432/unused",
            secret_key="x" * 32,
            participant_subnet="192.168.1.0/24",
        )
    )
    with TestClient(application) as client:
        response = client.get("/health")
    assert response.status_code == 200
    paths = set(application.openapi()["paths"])
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/admin/tournaments" in paths
