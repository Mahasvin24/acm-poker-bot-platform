from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from poker_bot_platform.auth.models import Account, Entrant, SessionRecord
from poker_bot_platform.domain import EntryKind, Role


class AuthRepositoryError(RuntimeError):
    pass


class AuthConflictError(AuthRepositoryError):
    pass


class AuthNotFoundError(AuthRepositoryError):
    pass


class AuthRepository(Protocol):
    async def create_account(self, email: str, password_hash: str, role: Role) -> Account: ...
    async def get_account_by_email(self, email: str) -> Account | None: ...
    async def get_account(self, account_id: str) -> Account | None: ...
    async def create_session(
        self, account_id: str, token_hash: str, expires_at: datetime
    ) -> SessionRecord: ...
    async def get_session(self, token_hash: str) -> SessionRecord | None: ...
    async def revoke_session(self, token_hash: str, revoked_at: datetime) -> None: ...
    async def create_entrant(
        self,
        account_id: str,
        tournament_id: str,
        kind: EntryKind,
        display_name: str,
    ) -> Entrant: ...
    async def get_entrant(self, account_id: str, tournament_id: str) -> Entrant | None: ...
    async def delete_entrant(self, entrant_id: str) -> None: ...
    async def configure_bot(
        self,
        entrant_id: str,
        ip: str,
        port: int,
        token_ciphertext: str,
    ) -> Entrant: ...
    async def mark_bot_verified(
        self,
        entrant_id: str,
        expected_token_ciphertext: str,
        verified_at: datetime,
    ) -> Entrant: ...


class InMemoryAuthRepository:
    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}
        self.sessions: dict[str, SessionRecord] = {}
        self.entrants: dict[str, Entrant] = {}

    async def create_account(self, email: str, password_hash: str, role: Role) -> Account:
        if await self.get_account_by_email(email) is not None:
            raise AuthConflictError("email is already registered")
        account = Account(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=password_hash,
            role=role,
            created_at=_utc_now(),
        )
        self.accounts[account.id] = account
        return account

    async def get_account_by_email(self, email: str) -> Account | None:
        return next((item for item in self.accounts.values() if item.email == email), None)

    async def get_account(self, account_id: str) -> Account | None:
        return self.accounts.get(account_id)

    async def create_session(
        self, account_id: str, token_hash: str, expires_at: datetime
    ) -> SessionRecord:
        if account_id not in self.accounts:
            raise AuthNotFoundError("account not found")
        session = SessionRecord(
            id=str(uuid.uuid4()),
            account_id=account_id,
            token_hash=token_hash,
            expires_at=expires_at,
            created_at=_utc_now(),
        )
        self.sessions[token_hash] = session
        return session

    async def get_session(self, token_hash: str) -> SessionRecord | None:
        return self.sessions.get(token_hash)

    async def revoke_session(self, token_hash: str, revoked_at: datetime) -> None:
        session = self.sessions.get(token_hash)
        if session is not None and session.revoked_at is None:
            self.sessions[token_hash] = session.model_copy(update={"revoked_at": revoked_at})

    async def create_entrant(
        self,
        account_id: str,
        tournament_id: str,
        kind: EntryKind,
        display_name: str,
    ) -> Entrant:
        if account_id not in self.accounts:
            raise AuthNotFoundError("account not found")
        if await self.get_entrant(account_id, tournament_id) is not None:
            raise AuthConflictError("account already has an entrant in this tournament")
        entrant = Entrant(
            id=str(uuid.uuid4()),
            account_id=account_id,
            tournament_id=tournament_id,
            kind=kind,
            display_name=display_name,
            created_at=_utc_now(),
        )
        self.entrants[entrant.id] = entrant
        return entrant

    async def get_entrant(self, account_id: str, tournament_id: str) -> Entrant | None:
        return next(
            (
                item
                for item in self.entrants.values()
                if item.account_id == account_id and item.tournament_id == tournament_id
            ),
            None,
        )

    async def delete_entrant(self, entrant_id: str) -> None:
        if entrant_id not in self.entrants:
            raise AuthNotFoundError("entrant not found")
        del self.entrants[entrant_id]

    async def configure_bot(
        self,
        entrant_id: str,
        ip: str,
        port: int,
        token_ciphertext: str,
    ) -> Entrant:
        entrant = self.entrants.get(entrant_id)
        if entrant is None:
            raise AuthNotFoundError("entrant not found")
        if entrant.kind is not EntryKind.BOT:
            raise AuthConflictError("human entrants cannot configure bot endpoints")
        updated = entrant.model_copy(
            update={
                "bot_ip": ip,
                "bot_port": port,
                "bot_token_ciphertext": token_ciphertext,
                "bot_verified_at": None,
            }
        )
        self.entrants[entrant_id] = updated
        return updated

    async def mark_bot_verified(
        self,
        entrant_id: str,
        expected_token_ciphertext: str,
        verified_at: datetime,
    ) -> Entrant:
        entrant = self.entrants.get(entrant_id)
        if entrant is None:
            raise AuthNotFoundError("entrant not found")
        if entrant.bot_token_ciphertext != expected_token_ciphertext:
            raise AuthConflictError("bot endpoint changed during verification")
        updated = entrant.model_copy(update={"bot_verified_at": verified_at})
        self.entrants[entrant_id] = updated
        return updated


def _utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
