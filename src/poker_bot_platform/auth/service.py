from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Network, IPv6Network
from typing import Protocol

from pwdlib import PasswordHash

from poker_bot_platform.auth.models import Account, BotProfile
from poker_bot_platform.auth.repository import (
    AuthConflictError,
    AuthNotFoundError,
    AuthRepository,
)
from poker_bot_platform.bots import BotEndpoint, VerificationOutcome
from poker_bot_platform.bots.messages import explain_failure
from poker_bot_platform.bots.network import validate_bot_endpoint
from poker_bot_platform.bots.tokens import (
    EncryptedTokenStore,
    generate_bearer_token,
    generate_verification_challenge,
)
from poker_bot_platform.domain import Role

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class InvalidCredentialsError(RuntimeError):
    pass


class InvalidSessionError(RuntimeError):
    pass


class BotVerificationError(RuntimeError):
    pass


class PasswordManager:
    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        self._password_hash = password_hash or PasswordHash.recommended()
        self._dummy_hash = self._password_hash.hash("not-a-real-user-password")

    def hash(self, password: str) -> str:
        _validate_password(password)
        hashed = self._password_hash.hash(password)
        if not hashed.startswith("$argon2id$"):
            raise RuntimeError("password backend must use Argon2id")
        return hashed

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._password_hash.verify(password, password_hash)
        except (TypeError, ValueError):
            return False

    def consume_dummy_verify(self, password: str) -> None:
        self.verify(password, self._dummy_hash)


@dataclass(frozen=True, slots=True)
class IssuedSession:
    account: Account
    token: str
    expires_at: datetime


class AuthService:
    def __init__(
        self,
        repository: AuthRepository,
        *,
        passwords: PasswordManager | None = None,
        session_lifetime: timedelta = timedelta(hours=12),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.passwords = passwords or PasswordManager()
        self.session_lifetime = session_lifetime
        self._clock = clock or (lambda: datetime.now(UTC))

    async def register(self, email: str, password: str) -> Account:
        normalized = normalize_email(email)
        return await self.repository.create_account(
            normalized,
            self.passwords.hash(password),
            Role.USER,
        )

    async def login(self, email: str, password: str) -> IssuedSession:
        normalized = normalize_email(email)
        account = await self.repository.get_account_by_email(normalized)
        if account is None:
            self.passwords.consume_dummy_verify(password)
            raise InvalidCredentialsError("invalid email or password")
        if not self.passwords.verify(password, account.password_hash):
            raise InvalidCredentialsError("invalid email or password")
        now = self._now()
        expires_at = now + self.session_lifetime
        token = secrets.token_urlsafe(32)
        await self.repository.create_session(account.id, hash_session_token(token), expires_at)
        return IssuedSession(account=account, token=token, expires_at=expires_at)

    async def logout(self, token: str) -> None:
        if token:
            await self.repository.revoke_session(hash_session_token(token), self._now())

    async def resolve_session(self, token: str | None) -> Account:
        if not token:
            raise InvalidSessionError("authentication required")
        now = self._now()
        session = await self.repository.get_session(hash_session_token(token))
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            raise InvalidSessionError("session is invalid or expired")
        account = await self.repository.get_account(session.account_id)
        if account is None:
            raise InvalidSessionError("session account no longer exists")
        return account

    async def change_password(
        self,
        account: Account,
        current_password: str,
        new_password: str,
    ) -> Account:
        if not self.passwords.verify(current_password, account.password_hash):
            raise InvalidCredentialsError("current password is incorrect")
        return await self.repository.set_password_hash(
            account.id,
            self.passwords.hash(new_password),
        )

    async def list_accounts(self) -> tuple[Account, ...]:
        return await self.repository.list_accounts()

    async def reset_password(self, account_id: str) -> str:
        """Set a temporary password, sign the account out everywhere, and return it once."""

        temporary = secrets.token_urlsafe(12)
        await self.repository.set_password_hash(account_id, self.passwords.hash(temporary))
        await self.repository.revoke_account_sessions(account_id, self._now())
        return temporary

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("auth clock must return a timezone-aware datetime")
        return value


class BotVerificationClient(Protocol):
    async def verify(
        self,
        endpoint: BotEndpoint,
        bearer_token: str,
        challenge: str,
    ) -> VerificationOutcome: ...


@dataclass(frozen=True, slots=True)
class BotTokenResult:
    profile: BotProfile
    bearer_token: str


class BotProfileService:
    """Owner-facing lifecycle for reusable participant bots."""

    def __init__(
        self,
        repository: AuthRepository,
        *,
        token_store: EncryptedTokenStore,
        participant_subnet: IPv4Network | IPv6Network,
        blocked_ips: tuple[str, ...] = (),
        verifier: BotVerificationClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.token_store = token_store
        self.participant_subnet = participant_subnet
        self.blocked_ips = blocked_ips
        self.verifier = verifier
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list(self, account_id: str) -> tuple[BotProfile, ...]:
        return await self.repository.list_bot_profiles(account_id)

    async def get(self, account_id: str, profile_id: str) -> BotProfile:
        return await self._owned(account_id, profile_id)

    async def create(self, account_id: str, name: str, ip: str, port: int) -> BotTokenResult:
        clean_name = _clean_name(name)
        endpoint = self._validate(ip, port)
        token = generate_bearer_token()
        profile = await self.repository.create_bot_profile(
            account_id,
            clean_name,
            str(endpoint.ip),
            endpoint.port,
            self.token_store.encrypt(token),
        )
        return BotTokenResult(profile=profile, bearer_token=token)

    async def update(
        self,
        account_id: str,
        profile_id: str,
        *,
        name: str | None = None,
        ip: str | None = None,
        port: int | None = None,
    ) -> BotProfile:
        current = await self._owned(account_id, profile_id)
        clean_name = _clean_name(name) if name is not None else None
        endpoint = None
        if ip is not None or port is not None:
            endpoint = self._validate(
                ip if ip is not None else current.bot_ip,
                port if port is not None else current.bot_port,
            )
        changed_endpoint = endpoint is not None and (
            str(endpoint.ip) != current.bot_ip or endpoint.port != current.bot_port
        )
        return await self.repository.update_bot_profile(
            profile_id,
            name=clean_name,
            ip=str(endpoint.ip) if changed_endpoint and endpoint else None,
            port=endpoint.port if changed_endpoint and endpoint else None,
        )

    async def rotate_token(self, account_id: str, profile_id: str) -> BotTokenResult:
        await self._owned(account_id, profile_id)
        token = generate_bearer_token()
        profile = await self.repository.update_bot_profile(
            profile_id,
            token_ciphertext=self.token_store.encrypt(token),
        )
        return BotTokenResult(profile=profile, bearer_token=token)

    async def delete(self, account_id: str, profile_id: str) -> None:
        await self._owned(account_id, profile_id)
        await self.repository.delete_bot_profile(profile_id)

    async def verify(self, account_id: str, profile_id: str) -> BotProfile:
        if self.verifier is None:
            raise BotVerificationError("bot verification client is not configured")
        profile = await self._owned(account_id, profile_id)
        try:
            endpoint = self._validate(profile.bot_ip, profile.bot_port)
        except ValueError as exc:
            await self.repository.record_bot_verification(
                profile_id,
                profile.bot_token_ciphertext,
                verified_at=None,
                error=str(exc),
            )
            raise BotVerificationError(str(exc)) from exc
        token = self.token_store.decrypt(profile.bot_token_ciphertext)
        outcome = await self.verifier.verify(endpoint, token, generate_verification_challenge())
        if not outcome.verified:
            message = explain_failure(outcome.failure_reason)
            await self.repository.record_bot_verification(
                profile_id,
                profile.bot_token_ciphertext,
                verified_at=None,
                error=message,
            )
            raise BotVerificationError(message)
        return await self.repository.record_bot_verification(
            profile_id,
            profile.bot_token_ciphertext,
            verified_at=self._now(),
            error=None,
        )

    def endpoint_for(self, profile: BotProfile) -> BotEndpoint:
        return self._validate(profile.bot_ip, profile.bot_port)

    def _validate(self, ip: str, port: int) -> BotEndpoint:
        return validate_bot_endpoint(
            ip,
            port,
            participant_subnet=self.participant_subnet,
            blocked_ips=self.blocked_ips,
        )

    async def _owned(self, account_id: str, profile_id: str) -> BotProfile:
        profile = await self.repository.get_bot_profile(profile_id)
        if profile is None or profile.account_id != account_id:
            raise AuthNotFoundError("bot not found")
        return profile

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("bot profile clock must return a timezone-aware datetime")
        return value


async def bootstrap_admin(
    repository: AuthRepository,
    email: str,
    password: str,
    *,
    passwords: PasswordManager | None = None,
) -> Account:
    """Deployment entry point for creating the first explicit admin account."""

    normalized = normalize_email(email)
    existing = await repository.get_account_by_email(normalized)
    if existing is not None:
        if existing.role is Role.ADMIN:
            return existing
        raise AuthConflictError("email already belongs to a non-admin account")
    manager = passwords or PasswordManager()
    return await repository.create_account(
        normalized,
        manager.hash(password),
        Role.ADMIN,
    )


def normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > 320 or not _EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("enter a valid email address")
    return normalized


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean_name(value: str) -> str:
    clean = " ".join(value.split())
    if not clean or len(clean) > 80:
        raise ValueError("name must contain between 1 and 80 characters")
    return clean


def _validate_password(password: str) -> None:
    if len(password) < 10 or len(password) > 256:
        raise ValueError("password must be between 10 and 256 characters")
