from __future__ import annotations

import asyncio
import hashlib
import random
import secrets
from collections.abc import Iterable, Mapping
from datetime import datetime

from poker_bot_platform.coordinator import TableCoordinator
from poker_bot_platform.domain import (
    EntryKind,
    HandSnapshot,
    MatchConfig,
    MatchStatus,
    SeatState,
    StartHandRequest,
)
from poker_bot_platform.match.models import (
    AuditEntry,
    MatchEntry,
    MatchPlayer,
    MatchState,
    MatchTable,
    Standing,
)
from poker_bot_platform.match.store import MatchStore

_STANDARD_DECK = tuple(f"{rank}{suit}" for rank in "23456789TJQKA" for suit in "cdhs")
# Seats spread evenly around the six-seat table so short-handed matches look balanced.
_SPREAD_SEATS = {
    2: (1, 4),
    3: (1, 3, 5),
    4: (1, 2, 4, 5),
    5: (1, 2, 3, 4, 5),
    6: (1, 2, 3, 4, 5, 6),
}
_TERMINAL = frozenset({MatchStatus.COMPLETED, MatchStatus.CANCELLED})


class MatchError(RuntimeError):
    pass


def deterministic_rng(seed_hex: str, purpose: str) -> random.Random:
    material = bytes.fromhex(seed_hex) + purpose.encode("utf-8")
    return random.Random(int.from_bytes(hashlib.sha256(material).digest()))


def clockwise_occupied(occupied: Iterable[int], after_seat: int) -> tuple[int, ...]:
    occupied_set = set(occupied)
    return tuple(
        seat
        for offset in range(1, 7)
        if (seat := ((after_seat - 1 + offset) % 6) + 1) in occupied_set
    )


class MatchCoordinator:
    """Serialized, durable state machine for one code-joined match.

    The coordinator emits ``StartHandRequest`` values; ``TableCoordinator`` remains the
    only component allowed to apply player actions.
    """

    def __init__(self, state: MatchState, store: MatchStore) -> None:
        self._state = state
        self._store = store
        self._lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        match_id: str,
        name: str,
        config: MatchConfig,
        join_code: str,
        store: MatchStore,
        *,
        created_by: str,
        created_at: datetime,
        seed_hex: str | None = None,
    ) -> MatchCoordinator:
        state = MatchState(
            match_id=match_id,
            name=name,
            join_code=join_code,
            config=config,
            seed_hex=seed_hex or secrets.token_hex(32),
            created_by=created_by,
            created_at=created_at,
            level_remaining_seconds=config.level_seconds,
        )
        await store.create(state, AuditEntry(actor_id=created_by, command="create_match"))
        return cls(state, store)

    @classmethod
    async def restore(cls, match_id: str, store: MatchStore) -> MatchCoordinator:
        return cls(await store.load(match_id), store)

    @property
    def state(self) -> MatchState:
        return self._state

    async def join(self, entry: MatchEntry, *, actor_id: str) -> MatchState:
        async with self._lock:
            self._require_status(MatchStatus.LOBBY, "the match has already started")
            state = self._state
            if len(state.entries) >= state.config.max_seats:
                raise MatchError("the match is full")
            if entry.kind is EntryKind.HUMAN and any(
                item.kind is EntryKind.HUMAN and item.account_id == entry.account_id
                for item in state.entries
            ):
                raise MatchError("you already have a human seat in this match")
            if entry.bot_profile_id is not None and any(
                item.bot_profile_id == entry.bot_profile_id for item in state.entries
            ):
                raise MatchError("that bot is already seated in this match")
            if any(
                item.display_name.casefold() == entry.display_name.casefold()
                for item in state.entries
            ):
                raise MatchError("that display name is already taken in this match")
            candidate = state.model_copy(update={"entries": (*state.entries, entry)})
            return await self._save(candidate, actor_id, "join_match")

    async def remove_entry(self, entry_id: str, *, actor_id: str) -> MatchState:
        async with self._lock:
            self._require_status(MatchStatus.LOBBY, "players can only leave before the start")
            if self._state.entry(entry_id) is None:
                raise MatchError("entry does not exist")
            candidate = self._state.model_copy(
                update={
                    "entries": tuple(
                        item for item in self._state.entries if item.entry_id != entry_id
                    )
                }
            )
            return await self._save(candidate, actor_id, "remove_entry")

    async def set_join_code(self, join_code: str | None, *, actor_id: str) -> MatchState:
        async with self._lock:
            if self._state.status in _TERMINAL:
                raise MatchError("the match is over")
            candidate = self._state.model_copy(update={"join_code": join_code})
            command = "revoke_join_code" if join_code is None else "set_join_code"
            return await self._save(candidate, actor_id, command)

    async def start(self, *, actor_id: str) -> MatchState:
        async with self._lock:
            self._require_status(MatchStatus.LOBBY, "the match has already started")
            state = self._state
            if len(state.entries) < 2:
                raise MatchError("at least two players must join before the match starts")
            rng = deterministic_rng(state.seed_hex, "seating")
            entries = list(state.entries)
            rng.shuffle(entries)
            players = tuple(
                MatchPlayer(
                    entry_id=entry.entry_id,
                    account_id=entry.account_id,
                    display_name=entry.display_name,
                    kind=entry.kind,
                    bot_profile_id=entry.bot_profile_id,
                    seat=seat,
                    stack=state.config.starting_stack,
                )
                for seat, entry in zip(_SPREAD_SEATS[len(entries)], entries, strict=True)
            )
            table = MatchTable(
                table_id=f"{state.match_id}-table",
                players=players,
                button_seat=rng.choice([player.seat for player in players]),
            )
            candidate = state.model_copy(
                update={
                    "status": MatchStatus.RUNNING,
                    "table": table,
                    "level_number": 1,
                    "level_remaining_seconds": state.config.level_seconds,
                }
            )
            candidate = self._start_next_hand(candidate, first=True)
            return await self._save(candidate, actor_id, "start_match")

    async def request_pause(self, *, actor_id: str) -> MatchState:
        async with self._lock:
            self._require_status(MatchStatus.RUNNING, "only a running match can be paused")
            table = self._state.table
            status = (
                MatchStatus.PAUSE_REQUESTED
                if table is not None and table.hand_in_progress
                else MatchStatus.PAUSED
            )
            candidate = self._state.model_copy(update={"status": status})
            return await self._save(candidate, actor_id, "request_pause")

    async def resume(self, *, actor_id: str) -> MatchState:
        async with self._lock:
            if self._state.status is MatchStatus.PAUSE_REQUESTED:
                candidate = self._state.model_copy(update={"status": MatchStatus.RUNNING})
                return await self._save(candidate, actor_id, "cancel_pause")
            self._require_status(MatchStatus.PAUSED, "only a paused match can resume")
            candidate = self._state.model_copy(update={"status": MatchStatus.RUNNING})
            candidate = self._start_next_hand(candidate)
            return await self._save(candidate, actor_id, "resume_match")

    async def request_end(self, *, actor_id: str) -> MatchState:
        """End after the current hand, ranking the remaining players by stack."""

        async with self._lock:
            state = self._state
            if state.status in _TERMINAL:
                raise MatchError("the match is already over")
            if state.status is MatchStatus.LOBBY:
                raise MatchError("cancel a match that has not started instead of ending it")
            if state.table is not None and state.table.hand_in_progress:
                candidate = state.model_copy(update={"end_requested": True})
                return await self._save(candidate, actor_id, "request_end")
            return await self._save(self._finalize(state), actor_id, "end_match")

    async def cancel(self, *, actor_id: str) -> MatchState:
        async with self._lock:
            state = self._state
            if state.status in _TERMINAL:
                raise MatchError("the match is already over")
            table = state.table
            candidate = state.model_copy(
                update={
                    "status": MatchStatus.CANCELLED,
                    "join_code": None,
                    "table": (
                        table.model_copy(
                            update={"hand_in_progress": False, "start_of_hand_stacks": {}}
                        )
                        if table is not None
                        else None
                    ),
                }
            )
            return await self._save(candidate, actor_id, "cancel_match")

    async def tick(self, elapsed_seconds: int, *, actor_id: str = "clock") -> MatchState:
        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds cannot be negative")
        async with self._lock:
            state = self._state
            level_seconds = state.config.level_seconds
            if (
                level_seconds is None
                or state.level_remaining_seconds is None
                or state.status not in {MatchStatus.RUNNING, MatchStatus.PAUSE_REQUESTED}
                or elapsed_seconds == 0
            ):
                return state
            remaining = state.level_remaining_seconds - elapsed_seconds
            level = state.level_number
            while remaining <= 0:
                level += 1
                remaining += level_seconds
            candidate = state.model_copy(
                update={"level_number": level, "level_remaining_seconds": remaining}
            )
            return await self._save(candidate, actor_id, "advance_clock")

    async def record_hand_completed(
        self,
        table_id: str,
        stacks: Mapping[str, int],
        *,
        actor_id: str = "table-coordinator",
    ) -> MatchState:
        async with self._lock:
            state = self._state
            if state.status not in {MatchStatus.RUNNING, MatchStatus.PAUSE_REQUESTED}:
                raise MatchError("match is not accepting hand results")
            table = self._require_table(table_id)
            if not table.hand_in_progress:
                raise MatchError("table has no hand in progress")
            expected = {player.entry_id for player in table.players}
            if set(stacks) != expected:
                raise MatchError("hand result must contain every seated entry exactly once")
            if any(
                isinstance(stack, bool) or not isinstance(stack, int) or stack < 0
                for stack in stacks.values()
            ):
                raise MatchError("hand result stacks must be non-negative integers")
            if sum(stacks.values()) != sum(player.stack for player in table.players):
                raise MatchError("hand result does not conserve chips")

            eliminated = [player for player in table.players if stacks[player.entry_id] == 0]
            standings = self._elimination_standings(table, eliminated)
            remaining = tuple(
                player.model_copy(update={"stack": stacks[player.entry_id]})
                for player in table.players
                if stacks[player.entry_id] > 0
            )
            button = table.button_seat
            if remaining and button not in {player.seat for player in remaining}:
                button = clockwise_occupied((p.seat for p in remaining), table.button_seat)[0]
            updated_table = table.model_copy(
                update={
                    "players": remaining or table.players,
                    "button_seat": button if remaining else table.button_seat,
                    "hand_in_progress": False,
                    "start_of_hand_stacks": {},
                }
            )
            candidate = state.model_copy(
                update={
                    "table": updated_table,
                    "standings": (*state.standings, *standings),
                }
            )
            if len(remaining) <= 1 or candidate.end_requested:
                candidate = self._finalize(candidate)
            elif candidate.status is MatchStatus.PAUSE_REQUESTED:
                candidate = candidate.model_copy(update={"status": MatchStatus.PAUSED})
            else:
                candidate = self._start_next_hand(candidate)
            return await self._save(candidate, actor_id, "record_hand_completed")

    async def mark_table_quarantined(
        self,
        table_id: str,
        *,
        actor_id: str = "table-coordinator",
    ) -> MatchState:
        async with self._lock:
            table = self._require_table(table_id)
            if table.quarantined:
                return self._state
            candidate = self._state.model_copy(
                update={
                    "table": table.model_copy(
                        update={
                            "quarantined": True,
                            "hand_in_progress": False,
                            "start_of_hand_stacks": {},
                        }
                    )
                }
            )
            if candidate.status is MatchStatus.PAUSE_REQUESTED:
                candidate = candidate.model_copy(update={"status": MatchStatus.PAUSED})
            return await self._save(candidate, actor_id, "mark_table_quarantined")

    def hand_request(self, *, table_version: int = 0) -> StartHandRequest:
        state = self._state
        table = state.table
        if table is None or not table.hand_in_progress:
            raise MatchError("table has no scheduled hand")
        level = state.config.level(table.hand_level_number)
        deck = list(_STANDARD_DECK)
        deterministic_rng(state.seed_hex, f"deck:{table.table_id}:{table.hand_number}").shuffle(
            deck
        )
        return StartHandRequest(
            match_id=state.match_id,
            table_id=table.table_id,
            hand_id=f"{table.table_id}-hand-{table.hand_number}",
            hand_number=table.hand_number,
            table_version=table_version,
            button_seat=table.button_seat,
            small_blind=level.small_blind,
            big_blind=level.big_blind,
            big_blind_ante=level.big_blind_ante,
            seats=tuple(
                SeatState(
                    seat=player.seat,
                    entrant_id=player.entry_id,
                    display_name=player.display_name,
                    kind=player.kind,
                    stack=player.stack,
                )
                for player in table.players
            ),
            deck_order=tuple(deck),
        )

    async def dispatch_hand(self, coordinator: TableCoordinator) -> HandSnapshot:
        """Dispatch the scheduled hand through the authoritative table coordinator."""

        table = self._state.table
        if table is None or coordinator.table_id != table.table_id:
            raise MatchError("coordinator targets a different table")
        runtime = coordinator.state.snapshot
        if table.hand_number == 1:
            if runtime is not None:
                raise MatchError("first hand cannot replace an initialized table")
            return await coordinator.start_table(self.hand_request())
        if runtime is None:
            raise MatchError("next hand requires a restored table coordinator")
        return await coordinator.start_next_hand(
            self.hand_request(table_version=runtime.table_version + 1)
        )

    def _start_next_hand(self, state: MatchState, *, first: bool = False) -> MatchState:
        table = state.table
        if table is None or table.quarantined or table.hand_in_progress or len(table.players) < 2:
            return state
        button = table.button_seat
        if not first:
            button = clockwise_occupied((player.seat for player in table.players), button)[0]
        return state.model_copy(
            update={
                "table": table.model_copy(
                    update={
                        "hand_number": table.hand_number + 1,
                        "hand_level_number": state.level_number,
                        "button_seat": button,
                        "hand_in_progress": True,
                        "start_of_hand_stacks": {
                            player.entry_id: player.stack for player in table.players
                        },
                    }
                )
            }
        )

    @staticmethod
    def _finalize(state: MatchState) -> MatchState:
        table = state.table
        remaining = sorted(
            table.players if table is not None else (),
            key=lambda player: (-player.stack, player.seat),
        )
        final: list[Standing] = []
        position = 1
        for index, player in enumerate(remaining):
            if index > 0 and player.stack < remaining[index - 1].stack:
                position = index + 1
            final.append(
                Standing(
                    entry_id=player.entry_id,
                    display_name=player.display_name,
                    kind=player.kind,
                    position=position,
                    final_stack=player.stack,
                )
            )
        return state.model_copy(
            update={
                "status": MatchStatus.COMPLETED,
                "join_code": None,
                "end_requested": False,
                "standings": tuple(
                    sorted(
                        (*final, *state.standings),
                        key=lambda item: (item.position, item.display_name),
                    )
                ),
                "table": (
                    table.model_copy(update={"hand_in_progress": False, "start_of_hand_stacks": {}})
                    if table is not None
                    else None
                ),
            }
        )

    @staticmethod
    def _elimination_standings(
        table: MatchTable,
        eliminated: list[MatchPlayer],
    ) -> tuple[Standing, ...]:
        if not eliminated:
            return ()
        survivors = len(table.players) - len(eliminated)
        stacks = table.start_of_hand_stacks
        return tuple(
            Standing(
                entry_id=player.entry_id,
                display_name=player.display_name,
                kind=player.kind,
                position=survivors
                + 1
                + sum(
                    1 for other in eliminated if stacks[other.entry_id] > stacks[player.entry_id]
                ),
                eliminated_hand_number=table.hand_number,
                final_stack=0,
            )
            for player in sorted(
                eliminated, key=lambda item: (-stacks[item.entry_id], item.entry_id)
            )
        )

    async def _save(self, candidate: MatchState, actor_id: str, command: str) -> MatchState:
        expected = self._state.revision
        candidate = candidate.model_copy(update={"revision": expected + 1})
        candidate = MatchState.model_validate(candidate.model_dump(mode="python"))
        await self._store.save(
            candidate,
            expected_revision=expected,
            audit=AuditEntry(actor_id=actor_id, command=command),
        )
        self._state = candidate
        return candidate

    def _require_table(self, table_id: str) -> MatchTable:
        table = self._state.table
        if table is None or table.table_id != table_id:
            raise MatchError("table does not exist")
        return table

    def _require_status(self, expected: MatchStatus, message: str) -> None:
        if self._state.status is not expected:
            raise MatchError(message)
