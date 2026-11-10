from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Protocol

from poker_bot_platform.auth.career import match_result_rows
from poker_bot_platform.auth.models import (
    Account,
    BotProfile,
    CareerSummary,
    LeaderboardEntry,
    MatchResultSummary,
    PasswordResetRequest,
    SessionRecord,
)
from poker_bot_platform.domain import EntryKind, Role
from poker_bot_platform.match.models import MatchState


class AuthRepositoryError(RuntimeError):
    pass


class AuthConflictError(AuthRepositoryError):
    pass


class AuthNotFoundError(AuthRepositoryError):
    pass


class AuthRepository(Protocol):
    async def create_account(
        self, email: str, password_hash: str, role: Role,
        participant_kind: EntryKind | None = None,
    ) -> Account: ...
    async def get_account_by_email(self, email: str) -> Account | None: ...
    async def get_account(self, account_id: str) -> Account | None: ...
    async def list_accounts(self) -> tuple[Account, ...]: ...
    async def mark_looking_for_match(self, account_id: str, at: datetime) -> Account: ...
    async def set_password_hash(self, account_id: str, password_hash: str) -> Account: ...
    async def create_session(
        self, account_id: str, token_hash: str, expires_at: datetime
    ) -> SessionRecord: ...
    async def get_session(self, token_hash: str) -> SessionRecord | None: ...
    async def revoke_session(self, token_hash: str, revoked_at: datetime) -> None: ...
    async def revoke_account_sessions(self, account_id: str, revoked_at: datetime) -> None: ...
    async def create_bot_profile(
        self,
        account_id: str,
        name: str,
        ip: str,
        port: int,
        token_ciphertext: str,
    ) -> BotProfile: ...
    async def get_bot_profile(self, profile_id: str) -> BotProfile | None: ...
    async def list_bot_profiles(self, account_id: str) -> tuple[BotProfile, ...]: ...
    async def update_bot_profile(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        ip: str | None = None,
        port: int | None = None,
        token_ciphertext: str | None = None,
    ) -> BotProfile: ...
    async def record_bot_verification(
        self,
        profile_id: str,
        expected_token_ciphertext: str,
        *,
        verified_at: datetime | None,
        error: str | None,
    ) -> BotProfile: ...
    async def delete_bot_profile(self, profile_id: str) -> None: ...
    async def update_account_profile(
        self, account_id: str, *, display_name: str | None
    ) -> Account: ...
    async def change_account_email(self, account_id: str, email: str) -> Account: ...
    async def delete_account(self, account_id: str, deleted_at: datetime) -> Account: ...
    async def upsert_password_reset_request(self, account_id: str) -> None: ...
    async def list_password_reset_requests(self) -> tuple[PasswordResetRequest, ...]: ...
    async def fulfill_password_reset_requests(self, account_id: str, fulfilled_at: datetime) -> None: ...
    async def career_summary(self, account_id: str) -> CareerSummary: ...
    async def match_results_for_account(self, account_id: str) -> tuple[MatchResultSummary, ...]: ...
    async def leaderboard(self, *, limit: int = 50) -> tuple[LeaderboardEntry, ...]: ...
    async def record_match_completion(self, state: MatchState) -> None: ...


class InMemoryAuthRepository:
    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}
        self.sessions: dict[str, SessionRecord] = {}
        self.bot_profiles: dict[str, BotProfile] = {}
        self.reset_requests: dict[str, PasswordResetRequest] = {}
        self.match_results: list[MatchResultSummary] = []

    async def create_account(
        self, email: str, password_hash: str, role: Role,
        participant_kind: EntryKind | None = None,
    ) -> Account:
        if await self.get_account_by_email(email) is not None:
            raise AuthConflictError("email is already registered")
        account = Account(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=password_hash,
            role=role,
            participant_kind=participant_kind,
            created_at=_utc_now(),
        )
        self.accounts[account.id] = account
        return account

    async def get_account_by_email(self, email: str) -> Account | None:
        return next(
            (item for item in self.accounts.values() if item.email == email and item.deleted_at is None),
            None,
        )

    async def get_account(self, account_id: str) -> Account | None:
        return self.accounts.get(account_id)

    async def list_accounts(self) -> tuple[Account, ...]:
        return tuple(sorted(self.accounts.values(), key=lambda item: item.created_at))

    async def set_password_hash(self, account_id: str, password_hash: str) -> Account:
        account = self.accounts.get(account_id)
        if account is None:
            raise AuthNotFoundError("account not found")
        updated = account.model_copy(update={"password_hash": password_hash})
        self.accounts[account_id] = updated
        return updated

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

    async def revoke_account_sessions(self, account_id: str, revoked_at: datetime) -> None:
        for token_hash, session in tuple(self.sessions.items()):
            if session.account_id == account_id and session.revoked_at is None:
                self.sessions[token_hash] = session.model_copy(update={"revoked_at": revoked_at})

    async def create_bot_profile(
        self,
        account_id: str,
        name: str,
        ip: str,
        port: int,
        token_ciphertext: str,
    ) -> BotProfile:
        if account_id not in self.accounts:
            raise AuthNotFoundError("account not found")
        if any(
            item.account_id == account_id
            for item in self.bot_profiles.values()
        ):
            raise AuthConflictError("you already have a bot; edit its settings instead")
        profile = BotProfile(
            id=str(uuid.uuid4()),
            account_id=account_id,
            name=name,
            bot_ip=ip,
            bot_port=port,
            bot_token_ciphertext=token_ciphertext,
            created_at=_utc_now(),
        )
        self.bot_profiles[profile.id] = profile
        return profile

    async def get_bot_profile(self, profile_id: str) -> BotProfile | None:
        return self.bot_profiles.get(profile_id)

    async def list_bot_profiles(self, account_id: str) -> tuple[BotProfile, ...]:
        return tuple(
            sorted(
                (item for item in self.bot_profiles.values() if item.account_id == account_id),
                key=lambda item: item.created_at,
            )
        )

    async def update_bot_profile(
        self,
        profile_id: str,
        *,
        name: str | None = None,
        ip: str | None = None,
        port: int | None = None,
        token_ciphertext: str | None = None,
    ) -> BotProfile:
        profile = self.bot_profiles.get(profile_id)
        if profile is None:
            raise AuthNotFoundError("bot not found")
        if name is not None and any(
            item.id != profile_id
            and item.account_id == profile.account_id
            and item.name.casefold() == name.casefold()
            for item in self.bot_profiles.values()
        ):
            raise AuthConflictError("you already have a bot with that name")
        update: dict[str, object] = {}
        if name is not None:
            update["name"] = name
        endpoint_changed = ip is not None or port is not None or token_ciphertext is not None
        if ip is not None:
            update["bot_ip"] = ip
        if port is not None:
            update["bot_port"] = port
        if token_ciphertext is not None:
            update["bot_token_ciphertext"] = token_ciphertext
        if endpoint_changed:
            update["verified_at"] = None
            update["last_verification_error"] = None
        updated = profile.model_copy(update=update)
        self.bot_profiles[profile_id] = updated
        return updated

    async def record_bot_verification(
        self,
        profile_id: str,
        expected_token_ciphertext: str,
        *,
        verified_at: datetime | None,
        error: str | None,
    ) -> BotProfile:
        profile = self.bot_profiles.get(profile_id)
        if profile is None:
            raise AuthNotFoundError("bot not found")
        if profile.bot_token_ciphertext != expected_token_ciphertext:
            raise AuthConflictError("bot endpoint changed during verification")
        updated = profile.model_copy(
            update={"verified_at": verified_at, "last_verification_error": error}
        )
        self.bot_profiles[profile_id] = updated
        return updated

    async def delete_bot_profile(self, profile_id: str) -> None:
        if self.bot_profiles.pop(profile_id, None) is None:
            raise AuthNotFoundError("bot not found")

    async def mark_looking_for_match(self, account_id: str, at: datetime) -> Account:
        account = self.accounts.get(account_id)
        if account is None or account.deleted_at is not None:
            raise AuthNotFoundError("account not found")
        updated = account.model_copy(update={"looking_for_match_at": at})
        self.accounts[account_id] = updated
        return updated

    async def update_account_profile(
        self, account_id: str, *, display_name: str | None
    ) -> Account:
        account = self.accounts.get(account_id)
        if account is None or account.deleted_at is not None:
            raise AuthNotFoundError("account not found")
        updated = account.model_copy(update={"display_name": display_name})
        self.accounts[account_id] = updated
        return updated

    async def change_account_email(self, account_id: str, email: str) -> Account:
        if await self.get_account_by_email(email) is not None:
            raise AuthConflictError("that email is already registered")
        account = self.accounts.get(account_id)
        if account is None or account.deleted_at is not None:
            raise AuthNotFoundError("account not found")
        updated = account.model_copy(update={"email": email})
        self.accounts[account_id] = updated
        return updated

    async def delete_account(self, account_id: str, deleted_at: datetime) -> Account:
        account = self.accounts.get(account_id)
        if account is None or account.deleted_at is not None:
            raise AuthNotFoundError("account not found")
        updated = account.model_copy(update={"deleted_at": deleted_at})
        self.accounts[account_id] = updated
        return updated

    async def upsert_password_reset_request(self, account_id: str) -> None:
        account = self.accounts.get(account_id)
        if account is None or account.deleted_at is not None:
            return
        self.reset_requests[account_id] = PasswordResetRequest(
            account_id=account_id,
            email=account.email,
            requested_at=_utc_now(),
        )

    async def list_password_reset_requests(self) -> tuple[PasswordResetRequest, ...]:
        return tuple(
            sorted(self.reset_requests.values(), key=lambda item: item.requested_at, reverse=True)
        )

    async def fulfill_password_reset_requests(self, account_id: str, fulfilled_at: datetime) -> None:
        self.reset_requests.pop(account_id, None)

    async def record_match_completion(self, state: MatchState) -> None:
        existing = {(item.match_id, item.entry_id) for item in self.match_results}
        for row in match_result_rows(state):
            if (row.match_id, row.entry_id) in existing:
                continue
            self.match_results.append(row)

    async def career_summary(self, account_id: str) -> CareerSummary:
        mine = [item for item in self.match_results if item.account_id == account_id]
        return CareerSummary(
            career_chip_total=sum(item.chip_delta for item in mine),
            matches_finished=len({item.match_id for item in mine}),
        )

    async def match_results_for_account(self, account_id: str) -> tuple[MatchResultSummary, ...]:
        return tuple(
            item
            for item in sorted(self.match_results, key=lambda row: row.match_id, reverse=True)
            if item.account_id == account_id
        )

    async def leaderboard(self, *, limit: int = 50) -> tuple[LeaderboardEntry, ...]:
        totals: dict[str, tuple[int, set[str]]] = {}
        for item in self.match_results:
            chips, matches = totals.get(item.account_id, (0, set()))
            matches.add(item.match_id)
            totals[item.account_id] = (chips + item.chip_delta, matches)
        rows: list[LeaderboardEntry] = []
        for account_id, (chips, match_ids) in totals.items():
            account = self.accounts.get(account_id)
            if account is None or account.deleted_at is not None:
                continue
            rows.append(
                LeaderboardEntry(
                    account_id=account_id,
                    email=account.email,
                    display_name=account.display_name,
                    career_chip_total=chips,
                    matches_finished=len(match_ids),
                )
            )
        rows.sort(key=lambda item: (-item.career_chip_total, item.email))
        return tuple(rows[:limit])


def _utc_now() -> datetime:
    return datetime.now(UTC)
