from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from poker_bot_platform.api.models import (
    AdminEntryResponse,
    AdminMatchResponse,
    AdminMatchSummaryResponse,
    LobbyEntryResponse,
    MatchPreviewResponse,
    MatchViewResponse,
    MyMatchResponse,
)
from poker_bot_platform.auth.models import Account, BotProfile
from poker_bot_platform.auth.repository import AuthRepository
from poker_bot_platform.auth.service import BotProfileService
from poker_bot_platform.bots import BotGateway
from poker_bot_platform.domain import EntryKind, MatchConfig, MatchStatus
from poker_bot_platform.integration.runtime import MatchRuntime, standing_responses
from poker_bot_platform.match import (
    MatchCoordinator,
    MatchEntry,
    MatchError,
    MatchRegistry,
    MatchState,
    MatchStoreError,
    format_join_code,
    normalize_join_code,
)

_HEALTH_CHECK_SECONDS = 1.5


class MatchNotFound(RuntimeError):
    pass


class MatchCommandError(RuntimeError):
    pass


class MatchService:
    """Application commands and views over code-joined matches."""

    def __init__(
        self,
        registry: MatchRegistry,
        accounts: AuthRepository,
        bots: BotProfileService,
        gateway: BotGateway,
        runtime: MatchRuntime,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._registry = registry
        self._accounts = accounts
        self._bots = bots
        self._gateway = gateway
        self._runtime = runtime
        self._clock = clock or (lambda: datetime.now(UTC))

    # Admin commands

    async def create(self, admin: Account, name: str, config: MatchConfig) -> AdminMatchResponse:
        clean = " ".join(name.split())
        if not clean:
            raise MatchCommandError("give the match a name")
        try:
            coordinator = await self._registry.create(clean, config, created_by=admin.id)
        except MatchStoreError as exc:
            raise MatchCommandError(str(exc)) from exc
        return await self._admin_view(coordinator.state)

    async def start(
        self, admin: Account, match_id: str, *, force: bool = False
    ) -> AdminMatchResponse:
        coordinator = await self._get(match_id)
        state = coordinator.state
        if state.status is not MatchStatus.LOBBY:
            raise MatchCommandError("the match has already started")
        problems = await self._bot_readiness_problems(state, check_health=not force)
        if problems:
            raise MatchCommandError(
                "Some bots are not ready: "
                + "; ".join(problems)
                + ". Fix them or start anyway; unresponsive bots check or fold automatically."
            )
        await self._run(coordinator.start(actor_id=admin.id))
        self._runtime.wake()
        return await self._admin_view(coordinator.state)

    async def pause(self, admin: Account, match_id: str) -> AdminMatchResponse:
        coordinator = await self._get(match_id)
        await self._run(coordinator.request_pause(actor_id=admin.id))
        return await self._admin_view(coordinator.state)

    async def resume(self, admin: Account, match_id: str) -> AdminMatchResponse:
        coordinator = await self._get(match_id)
        await self._run(coordinator.resume(actor_id=admin.id))
        self._runtime.wake()
        return await self._admin_view(coordinator.state)

    async def end(self, admin: Account, match_id: str) -> AdminMatchResponse:
        coordinator = await self._get(match_id)
        await self._run(coordinator.request_end(actor_id=admin.id))
        return await self._admin_view(coordinator.state)

    async def cancel(self, admin: Account, match_id: str) -> AdminMatchResponse:
        coordinator = await self._get(match_id)
        await self._run(coordinator.cancel(actor_id=admin.id))
        return await self._admin_view(coordinator.state)

    async def regenerate_code(self, admin: Account, match_id: str) -> AdminMatchResponse:
        coordinator = await self._get(match_id)
        if coordinator.state.status in {MatchStatus.COMPLETED, MatchStatus.CANCELLED}:
            raise MatchCommandError("the match is over")
        try:
            await self._registry.regenerate_code(match_id, actor_id=admin.id)
        except (MatchError, MatchStoreError) as exc:
            raise MatchCommandError(str(exc)) from exc
        return await self._admin_view(coordinator.state)

    async def revoke_code(self, admin: Account, match_id: str) -> AdminMatchResponse:
        coordinator = await self._get(match_id)
        await self._run(coordinator.set_join_code(None, actor_id=admin.id))
        return await self._admin_view(coordinator.state)

    async def kick(self, admin: Account, match_id: str, entry_id: str) -> AdminMatchResponse:
        coordinator = await self._get(match_id)
        await self._run(coordinator.remove_entry(entry_id, actor_id=admin.id))
        return await self._admin_view(coordinator.state)

    async def admin_list(self) -> tuple[AdminMatchSummaryResponse, ...]:
        states = await self._registry.list_states()
        return tuple(
            AdminMatchSummaryResponse(
                match_id=state.match_id,
                name=state.name,
                status=state.status,
                join_code=format_join_code(state.join_code) if state.join_code else None,
                seats_taken=len(state.entries),
                max_seats=state.config.max_seats,
                players_remaining=state.players_remaining,
                created_at=state.created_at,
            )
            for state in sorted(states, key=lambda item: item.created_at, reverse=True)
        )

    async def admin_detail(self, match_id: str) -> AdminMatchResponse:
        return await self._admin_view((await self._get(match_id)).state)

    # Player commands

    async def preview(self, code: str) -> MatchPreviewResponse:
        coordinator = await self._by_code(code)
        state = coordinator.state
        reason = None
        if state.status is not MatchStatus.LOBBY:
            reason = "this match has already started"
        elif len(state.entries) >= state.config.max_seats:
            reason = "this match is full"
        return MatchPreviewResponse(
            match_id=state.match_id,
            name=state.name,
            status=state.status,
            seats_taken=len(state.entries),
            max_seats=state.config.max_seats,
            config=state.config,
            joinable=reason is None,
            reason=reason,
        )

    async def join(
        self,
        account: Account,
        code: str,
        kind: EntryKind,
        display_name: str | None,
        bot_profile_id: str | None,
    ) -> MatchViewResponse:
        coordinator = await self._by_code(code)
        profile: BotProfile | None = None
        if kind is EntryKind.BOT:
            assert bot_profile_id is not None
            profile = await self._accounts.get_bot_profile(bot_profile_id)
            if profile is None or profile.account_id != account.id:
                raise MatchCommandError("choose one of your own bots")
            if profile.verified_at is None:
                raise MatchCommandError(
                    "verify this bot from My Bots before joining; the platform must reach it first"
                )
        name = " ".join((display_name or (profile.name if profile else "")).split())
        if not name or len(name) > 80:
            raise MatchCommandError("enter a display name between 1 and 80 characters")
        entry = MatchEntry(
            entry_id=str(uuid.uuid4()),
            account_id=account.id,
            display_name=name,
            kind=kind,
            bot_profile_id=profile.id if profile else None,
            joined_at=self._clock(),
        )
        await self._run(coordinator.join(entry, actor_id=account.id))
        return await self.view(account, coordinator.state.match_id)

    async def leave(self, account: Account, match_id: str, entry_id: str) -> None:
        coordinator = await self._get(match_id)
        entry = coordinator.state.entry(entry_id)
        if entry is None or entry.account_id != account.id:
            raise MatchNotFound("entry not found")
        await self._run(coordinator.remove_entry(entry_id, actor_id=account.id))

    async def view(self, account: Account, match_id: str) -> MatchViewResponse:
        state = (await self._get(match_id)).state
        if not any(entry.account_id == account.id for entry in state.entries):
            raise MatchNotFound("you have not joined this match")
        ready = await self._readiness(state, account.id)
        return MatchViewResponse(
            match_id=state.match_id,
            name=state.name,
            status=state.status,
            max_seats=state.config.max_seats,
            config=state.config,
            entries=tuple(
                LobbyEntryResponse(
                    entry_id=entry.entry_id,
                    display_name=entry.display_name,
                    kind=entry.kind,
                    mine=entry.account_id == account.id,
                    bot_ready=ready.get(entry.entry_id),
                )
                for entry in state.entries
            ),
            standings=standing_responses(state),
            level_number=state.level_number,
            level_remaining_seconds=state.level_remaining_seconds,
            end_requested=state.end_requested,
            created_at=state.created_at,
        )

    async def my_matches(self, account: Account) -> tuple[MyMatchResponse, ...]:
        states = await self._registry.list_states()
        mine = [
            state
            for state in states
            if any(entry.account_id == account.id for entry in state.entries)
        ]
        order = {
            MatchStatus.RUNNING: 0,
            MatchStatus.PAUSE_REQUESTED: 0,
            MatchStatus.PAUSED: 1,
            MatchStatus.LOBBY: 2,
            MatchStatus.COMPLETED: 3,
            MatchStatus.CANCELLED: 4,
        }
        mine.sort(key=lambda item: (order[item.status], -item.created_at.timestamp()))
        return tuple(
            MyMatchResponse(
                match_id=state.match_id,
                name=state.name,
                status=state.status,
                seats_taken=len(state.entries),
                max_seats=state.config.max_seats,
                my_entries=tuple(
                    LobbyEntryResponse(
                        entry_id=entry.entry_id,
                        display_name=entry.display_name,
                        kind=entry.kind,
                        mine=True,
                    )
                    for entry in state.entries
                    if entry.account_id == account.id
                ),
                created_at=state.created_at,
            )
            for state in mine
        )

    # Helpers

    async def _get(self, match_id: str) -> MatchCoordinator:
        try:
            return await self._registry.get(match_id)
        except MatchStoreError as exc:
            raise MatchNotFound("match does not exist") from exc

    async def _by_code(self, code: str) -> MatchCoordinator:
        try:
            normalized = normalize_join_code(code)
        except ValueError as exc:
            raise MatchNotFound(str(exc)) from exc
        coordinator = await self._registry.find_by_code(normalized)
        if coordinator is None:
            raise MatchNotFound("no open match uses that code; check it with the organizer")
        return coordinator

    @staticmethod
    async def _run(command: object) -> None:
        try:
            await command  # type: ignore[misc]
        except MatchError as exc:
            raise MatchCommandError(str(exc)) from exc
        except MatchStoreError as exc:
            raise MatchCommandError("the match could not be saved; try again") from exc

    async def _readiness(self, state: MatchState, account_id: str) -> dict[str, bool]:
        ready: dict[str, bool] = {}
        for entry in state.entries:
            if entry.account_id != account_id or entry.bot_profile_id is None:
                continue
            profile = await self._accounts.get_bot_profile(entry.bot_profile_id)
            ready[entry.entry_id] = profile is not None and profile.verified_at is not None
        return ready

    async def _bot_readiness_problems(
        self,
        state: MatchState,
        *,
        check_health: bool,
    ) -> list[str]:
        problems: list[str] = []
        probes: list[tuple[str, BotProfile]] = []
        for entry in state.entries:
            if entry.kind is not EntryKind.BOT or entry.bot_profile_id is None:
                continue
            profile = await self._accounts.get_bot_profile(entry.bot_profile_id)
            if profile is None:
                problems.append(f"{entry.display_name} was deleted by its owner")
            elif profile.verified_at is None:
                problems.append(f"{entry.display_name} is not verified")
            elif check_health:
                probes.append((entry.display_name, profile))
        if probes:
            results = await asyncio.gather(*(self._healthy(profile) for _, profile in probes))
            problems.extend(
                f"{name} did not answer its health check"
                for (name, _), healthy in zip(probes, results, strict=True)
                if not healthy
            )
        return problems

    async def _healthy(self, profile: BotProfile) -> bool:
        try:
            endpoint = self._bots.endpoint_for(profile)
        except ValueError:
            return False
        return (
            await self._gateway.health(endpoint, timeout_seconds=_HEALTH_CHECK_SECONDS) is not None
        )

    async def _admin_view(self, state: MatchState) -> AdminMatchResponse:
        accounts = {account.id: account for account in await self._accounts.list_accounts()}
        players = {player.entry_id: player for player in state.table.players} if state.table else {}
        standings = {item.entry_id for item in state.standings}
        entries: list[AdminEntryResponse] = []
        for entry in state.entries:
            profile = (
                await self._accounts.get_bot_profile(entry.bot_profile_id)
                if entry.bot_profile_id
                else None
            )
            stats = self._runtime.bot_stats(entry.bot_profile_id) if entry.bot_profile_id else None
            activity = self._runtime.entry_activity(entry.entry_id)
            player = players.get(entry.entry_id)
            entry_state: Literal["lobby", "seated", "eliminated", "finished"]
            if state.status is MatchStatus.LOBBY:
                entry_state = "lobby"
            elif entry.entry_id in standings and state.status is MatchStatus.COMPLETED:
                entry_state = "finished"
            elif entry.entry_id in standings:
                entry_state = "eliminated"
            else:
                entry_state = "seated"
            account = accounts.get(entry.account_id)
            entries.append(
                AdminEntryResponse(
                    entry_id=entry.entry_id,
                    display_name=entry.display_name,
                    kind=entry.kind,
                    account_email=account.email if account else None,
                    bot_name=profile.name if profile else None,
                    bot_ready=(profile.verified_at is not None) if profile else None,
                    bot_endpoint=f"{profile.bot_ip}:{profile.bot_port}" if profile else None,
                    state=entry_state,
                    seat=player.seat if player else None,
                    stack=player.stack if player and entry_state == "seated" else None,
                    away=activity.away,
                    last_seen_at=activity.last_seen_at,
                    bot_decisions=stats.decisions if stats else 0,
                    bot_failures=sum(stats.failures.values()) if stats else 0,
                    bot_consecutive_failures=stats.consecutive_failures if stats else 0,
                )
            )
        return AdminMatchResponse(
            match_id=state.match_id,
            name=state.name,
            status=state.status,
            join_code=format_join_code(state.join_code) if state.join_code else None,
            config=state.config,
            entries=tuple(entries),
            standings=standing_responses(state),
            hand_number=state.table.hand_number if state.table else 0,
            level_number=state.level_number,
            level_remaining_seconds=state.level_remaining_seconds,
            end_requested=state.end_requested,
            table_quarantined=bool(state.table and state.table.quarantined),
            created_at=state.created_at,
            revision=state.revision,
        )
