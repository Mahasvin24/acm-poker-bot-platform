from __future__ import annotations

from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

import pytest

from poker_bot_platform.auth import (
    AuthConflictError,
    AuthNotFoundError,
    AuthService,
    BotProfileService,
    InMemoryAuthRepository,
    PasswordManager,
    bootstrap_admin,
)
from poker_bot_platform.auth.service import (
    BotVerificationError,
    InvalidCredentialsError,
    InvalidSessionError,
)
from poker_bot_platform.bots import VerificationOutcome
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.domain import FailureReason, Role

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


class FailingVerifier:
    async def verify(self, *_args: object) -> VerificationOutcome:
        return VerificationOutcome(verified=False, failure_reason=FailureReason.HTTP_STATUS)


def bot_service(
    repository: InMemoryAuthRepository,
    verifier: object | None = None,
    token_store: EncryptedTokenStore | None = None,
) -> BotProfileService:
    return BotProfileService(
        repository,
        token_store=token_store or EncryptedTokenStore.from_deployment_secret("s" * 32),
        participant_subnet=ip_network("192.168.0.0/16"),
        blocked_ips=("192.168.1.1",),
        verifier=verifier,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_bot_profiles_encrypt_tokens_verify_and_are_reusable() -> None:
    repository = InMemoryAuthRepository()
    account = await AuthService(repository).register("bot@example.com", "long-enough-password")
    verifier = SuccessfulVerifier()
    token_store = EncryptedTokenStore.from_deployment_secret("s" * 32)
    service = bot_service(repository, verifier, token_store)

    created = await service.create(account.id, "  River   Runner ", "192.168.1.25", 8001)
    assert created.profile.name == "River Runner"
    assert created.bearer_token not in created.profile.bot_token_ciphertext
    assert token_store.decrypt(created.profile.bot_token_ciphertext) == created.bearer_token
    second = await service.create(account.id, "Second Bot", "192.168.1.26", 8002)
    assert [item.id for item in await service.list(account.id)] == [
        created.profile.id,
        second.profile.id,
    ]

    with pytest.raises(AuthConflictError):
        await service.create(account.id, "river runner", "192.168.1.27", 8003)

    verified = await service.verify(account.id, created.profile.id)
    assert verified.verified_at == NOW
    assert verifier.presented_token == created.bearer_token

    moved = await service.update(account.id, created.profile.id, ip="192.168.1.30")
    assert moved.verified_at is None
    renamed = await service.update(account.id, created.profile.id, name="Renamed")
    assert renamed.bot_ip == "192.168.1.30"

    rotated = await service.rotate_token(account.id, created.profile.id)
    assert rotated.bearer_token != created.bearer_token
    assert token_store.decrypt(rotated.profile.bot_token_ciphertext) == rotated.bearer_token


@pytest.mark.asyncio
async def test_bot_endpoint_validation_and_verification_errors_are_plain_language() -> None:
    repository = InMemoryAuthRepository()
    account = await AuthService(repository).register("bot@example.com", "long-enough-password")
    service = bot_service(repository, FailingVerifier())

    with pytest.raises(ValueError, match="event network"):
        await service.create(account.id, "Elsewhere", "10.0.0.5", 8001)
    with pytest.raises(ValueError, match="infrastructure"):
        await service.create(account.id, "Router", "192.168.1.1", 8001)

    created = await service.create(account.id, "Bot", "192.168.1.25", 8001)
    with pytest.raises(BotVerificationError, match="bearer token"):
        await service.verify(account.id, created.profile.id)
    stored = await repository.get_bot_profile(created.profile.id)
    assert stored is not None
    assert stored.verified_at is None
    assert stored.last_verification_error is not None


@pytest.mark.asyncio
async def test_bots_are_private_to_their_owner() -> None:
    repository = InMemoryAuthRepository()
    auth = AuthService(repository)
    owner = await auth.register("owner@example.com", "long-enough-password")
    other = await auth.register("other@example.com", "long-enough-password")
    service = bot_service(repository, SuccessfulVerifier())
    created = await service.create(owner.id, "Bot", "192.168.1.25", 8001)

    with pytest.raises(AuthNotFoundError):
        await service.verify(other.id, created.profile.id)
    with pytest.raises(AuthNotFoundError):
        await service.delete(other.id, created.profile.id)
    await service.delete(owner.id, created.profile.id)
    assert await service.list(owner.id) == ()


@pytest.mark.asyncio
async def test_password_change_and_admin_reset_revoke_sessions() -> None:
    repository = InMemoryAuthRepository()
    auth = AuthService(repository, clock=lambda: NOW)
    account = await auth.register("person@example.com", "long-enough-password")
    issued = await auth.login("person@example.com", "long-enough-password")

    with pytest.raises(InvalidCredentialsError):
        await auth.change_password(account, "wrong-password", "brand-new-password")
    changed = await auth.change_password(account, "long-enough-password", "brand-new-password")
    await auth.login("person@example.com", "brand-new-password")

    temporary = await auth.reset_password(changed.id)
    with pytest.raises(InvalidSessionError):
        await auth.resolve_session(issued.token)
    with pytest.raises(InvalidCredentialsError):
        await auth.login("person@example.com", "brand-new-password")
    await auth.login("person@example.com", temporary)
