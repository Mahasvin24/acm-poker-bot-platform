from __future__ import annotations

from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

import pytest

from poker_bot_platform.auth import (
    AuthConflictError,
    AuthService,
    EntrantService,
    InMemoryAuthRepository,
    PasswordManager,
    bootstrap_admin,
)
from poker_bot_platform.auth.service import InvalidCredentialsError, InvalidSessionError
from poker_bot_platform.bots import VerificationOutcome
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.domain import EntryKind, Role

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


class SuccessfulVerifier:
    def __init__(self) -> None:
        self.presented_token: str | None = None

    async def verify(
        self, endpoint: object, bearer_token: str, challenge: str
    ) -> VerificationOutcome:
        assert len(challenge) >= 32
        self.presented_token = bearer_token
        return VerificationOutcome(verified=True)


def test_password_manager_uses_argon2id() -> None:
    passwords = PasswordManager()
    hashed = passwords.hash("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert passwords.verify("correct horse battery staple", hashed)
    assert not passwords.verify("wrong password", hashed)


@pytest.mark.asyncio
async def test_registration_login_stores_only_session_hash_and_logout_revokes() -> None:
    repository = InMemoryAuthRepository()
    current = NOW
    auth = AuthService(repository, clock=lambda: current)
    account = await auth.register(" Person@Example.COM ", "long-enough-password")
    assert account.email == "person@example.com"
    assert account.role is Role.USER
    assert account.password_hash.startswith("$argon2id$")

    issued = await auth.login("person@example.com", "long-enough-password")
    assert issued.token not in repository.sessions
    assert all(issued.token not in item.token_hash for item in repository.sessions.values())
    assert await auth.resolve_session(issued.token) == account

    await auth.logout(issued.token)
    with pytest.raises(InvalidSessionError):
        await auth.resolve_session(issued.token)


@pytest.mark.asyncio
async def test_invalid_credentials_and_expired_session() -> None:
    repository = InMemoryAuthRepository()
    current = NOW
    auth = AuthService(
        repository,
        session_lifetime=timedelta(minutes=5),
        clock=lambda: current,
    )
    await auth.register("person@example.com", "long-enough-password")
    with pytest.raises(InvalidCredentialsError):
        await auth.login("person@example.com", "incorrect-password")
    with pytest.raises(InvalidCredentialsError):
        await auth.login("missing@example.com", "incorrect-password")

    issued = await auth.login("person@example.com", "long-enough-password")
    current = NOW + timedelta(minutes=5)
    with pytest.raises(InvalidSessionError):
        await auth.resolve_session(issued.token)


@pytest.mark.asyncio
async def test_bootstrap_is_explicit_and_does_not_grant_admin_by_email_pattern() -> None:
    repository = InMemoryAuthRepository()
    auth = AuthService(repository)
    ordinary = await auth.register("mahasvin@admin.com", "long-enough-password")
    assert ordinary.role is Role.USER
    with pytest.raises(AuthConflictError):
        await bootstrap_admin(repository, ordinary.email, "another-long-password")

    admin = await bootstrap_admin(repository, "owner@example.com", "another-long-password")
    assert admin.role is Role.ADMIN
    assert await bootstrap_admin(repository, "OWNER@example.com", "ignored-password") == admin


@pytest.mark.asyncio
async def test_one_entrant_per_account_and_bot_token_is_encrypted_and_verified() -> None:
    repository = InMemoryAuthRepository()
    account = await AuthService(repository).register(
        "bot@example.com",
        "long-enough-password",
    )
    verifier = SuccessfulVerifier()
    token_store = EncryptedTokenStore.from_deployment_secret("s" * 32)
    service = EntrantService(
        repository,
        token_store=token_store,
        participant_subnet=ip_network("192.168.0.0/16"),
        blocked_ips=("192.168.1.1",),
        verifier=verifier,
        clock=lambda: NOW,
    )
    entrant = await service.register(
        account.id,
        "tournament-1",
        EntryKind.BOT,
        "Example Bot",
    )
    with pytest.raises(AuthConflictError):
        await service.register(account.id, "tournament-1", EntryKind.HUMAN, "Duplicate")

    configured = await service.configure_bot(
        account.id,
        "tournament-1",
        "192.168.1.25",
        8001,
    )
    assert configured.entrant.id == entrant.id
    assert configured.bearer_token not in (configured.entrant.bot_token_ciphertext or "")
    assert (
        token_store.decrypt(configured.entrant.bot_token_ciphertext or "")
        == configured.bearer_token
    )

    verified = await service.verify_bot(account.id, "tournament-1")
    assert verified.bot_verified_at == NOW
    assert verifier.presented_token == configured.bearer_token


@pytest.mark.asyncio
async def test_human_cannot_configure_bot_endpoint() -> None:
    repository = InMemoryAuthRepository()
    account = await AuthService(repository).register(
        "human@example.com",
        "long-enough-password",
    )
    service = EntrantService(
        repository,
        token_store=EncryptedTokenStore.from_deployment_secret("s" * 32),
        participant_subnet=ip_network("192.168.0.0/16"),
    )
    await service.register(account.id, "tournament-1", EntryKind.HUMAN, "Human")
    with pytest.raises(AuthConflictError):
        await service.configure_bot(account.id, "tournament-1", "192.168.1.25", 8001)
