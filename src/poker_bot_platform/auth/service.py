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

from poker_bot_platform.auth.models import Account, Entrant
from poker_bot_platform.auth.repository import (
    AuthConflictError,
    AuthNotFoundError,
    AuthRepository,
)
from poker_bot_platform.bots import BotEndpoint, VerificationOutcome
from poker_bot_platform.bots.network import validate_bot_endpoint
from poker_bot_platform.bots.tokens import (
    EncryptedTokenStore,
    generate_bearer_token,
    generate_verification_challenge,
)
from poker_bot_platform.domain import EntryKind, Role

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
class BotRegistrationResult:
    entrant: Entrant
    bearer_token: str


class EntrantService:
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

    async def register(
        self,
        account_id: str,
        tournament_id: str,
        kind: EntryKind,
        display_name: str,
    ) -> Entrant:
        clean_name = display_name.strip()
        if not clean_name or len(clean_name) > 80:
            raise ValueError("display name must contain between 1 and 80 characters")
        return await self.repository.create_entrant(
            account_id,
            tournament_id,
            kind,
            clean_name,
        )

    async def current(self, account_id: str, tournament_id: str) -> Entrant:
        return await self._owned_entrant(account_id, tournament_id)

    async def configure_bot(
        self,
        account_id: str,
        tournament_id: str,
        ip: str,
        port: int,
    ) -> BotRegistrationResult:
        entrant = await self._owned_entrant(account_id, tournament_id)
        if entrant.kind is not EntryKind.BOT:
            raise AuthConflictError("only bot entrants can configure an endpoint")
        endpoint = validate_bot_endpoint(
            ip,
            port,
            participant_subnet=self.participant_subnet,
            blocked_ips=self.blocked_ips,
        )
        token = generate_bearer_token()
        updated = await self.repository.configure_bot(
            entrant.id,
            str(endpoint.ip),
            endpoint.port,
            self.token_store.encrypt(token),
        )
        return BotRegistrationResult(entrant=updated, bearer_token=token)

    async def verify_bot(self, account_id: str, tournament_id: str) -> Entrant:
        if self.verifier is None:
            raise BotVerificationError("bot verification client is not configured")
        entrant = await self._owned_entrant(account_id, tournament_id)
        if (
            entrant.kind is not EntryKind.BOT
            or entrant.bot_ip is None
            or entrant.bot_port is None
            or entrant.bot_token_ciphertext is None
        ):
            raise BotVerificationError("bot endpoint is not configured")
        endpoint = validate_bot_endpoint(
            entrant.bot_ip,
            entrant.bot_port,
            participant_subnet=self.participant_subnet,
            blocked_ips=self.blocked_ips,
        )
        token = self.token_store.decrypt(entrant.bot_token_ciphertext)
        outcome = await self.verifier.verify(
            endpoint,
            token,
            generate_verification_challenge(),
        )
        if not outcome.verified:
            reason = outcome.failure_reason.value if outcome.failure_reason else "unknown"
            raise BotVerificationError(f"bot verification failed: {reason}")
        return await self.repository.mark_bot_verified(
            entrant.id,
            entrant.bot_token_ciphertext,
            self._now(),
        )

    async def _owned_entrant(self, account_id: str, tournament_id: str) -> Entrant:
        entrant = await self.repository.get_entrant(account_id, tournament_id)
        if entrant is None:
            raise AuthNotFoundError("entrant not found")
        return entrant

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise RuntimeError("entrant clock must return a timezone-aware datetime")
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
        raise ValueError("invalid email address")
    return normalized


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_password(password: str) -> None:
    if len(password) < 10 or len(password) > 256:
        raise ValueError("password must be between 10 and 256 characters")
