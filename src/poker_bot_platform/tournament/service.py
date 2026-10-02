from __future__ import annotations

import asyncio
import math
import secrets
from collections.abc import Mapping

from poker_bot_platform.coordinator import TableCoordinator
from poker_bot_platform.domain import (
    EntryKind,
    HandSnapshot,
    SeatState,
    StartHandRequest,
    TournamentConfig,
    TournamentStatus,
)
from poker_bot_platform.persistence import TableRepository
from poker_bot_platform.tournament.helpers import (
    clockwise_occupied,
    deterministic_rng,
    next_big_blind_player,
    next_button,
    table_sort_key,
    worst_legal_vacancy,
)
from poker_bot_platform.tournament.models import (
    AuditEntry,
    Entrant,
    Standing,
    TournamentPlayer,
    TournamentState,
    TournamentTable,
)
from poker_bot_platform.tournament.store import TournamentStore

_STANDARD_DECK = tuple(f"{rank}{suit}" for rank in "23456789TJQKA" for suit in "cdhs")


class TournamentError(RuntimeError):
    pass


class TournamentCoordinator:
    """Serialized, durable tournament state machine.

    Tournament scheduling is intentionally separate from a table's poker rules. The
    coordinator emits ``StartHandRequest`` values; ``TableCoordinator`` remains the
    only component allowed to apply player actions.
    """

    def __init__(
        self,
        state: TournamentState,
        store: TournamentStore,
        table_repository: TableRepository,
    ) -> None:
        self._state = state
        self._store = store
        self._table_repository = table_repository
        self._lock = asyncio.Lock()

    @classmethod
    async def create(
        cls,
        tournament_id: str,
        config: TournamentConfig,
        store: TournamentStore,
        table_repository: TableRepository,
        *,
        seed_hex: str | None = None,
        actor_id: str = "system",
    ) -> TournamentCoordinator:
        seed_hex = seed_hex or secrets.token_hex(32)
        state = TournamentState(
            tournament_id=tournament_id,
            config=config,
            seed_hex=seed_hex,
            phase_remaining_seconds=config.level(1).duration_seconds,
        )
        await table_repository.create_tournament(
            tournament_id,
            config.model_dump(mode="json"),
            status=TournamentStatus.DRAFT,
        )
        await store.create(state, AuditEntry(actor_id=actor_id, command="create_tournament"))
        return cls(state, store, table_repository)

    @classmethod
    async def restore(
        cls,
        tournament_id: str,
        store: TournamentStore,
        table_repository: TableRepository,
    ) -> TournamentCoordinator:
        return cls(await store.load(tournament_id), store, table_repository)

    @property
    def state(self) -> TournamentState:
        return self._state

    async def update_config(
        self,
        config: TournamentConfig,
        *,
        actor_id: str,
    ) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.DRAFT)
            candidate = self._state.model_copy(
                update={
                    "config": config,
                    "phase_remaining_seconds": config.level(1).duration_seconds,
                }
            )
            return await self._save(candidate, actor_id, "update_config")

    async def open_registration(self, *, actor_id: str) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.DRAFT)
            candidate = self._state.model_copy(
                update={"status": TournamentStatus.REGISTRATION_OPEN}
            )
            return await self._save(candidate, actor_id, "open_registration")

    async def register(self, entrant: Entrant, *, actor_id: str) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.REGISTRATION_OPEN)
            if len(self._state.entrants) >= self._state.config.max_players:
                raise TournamentError("tournament is full")
            if any(item.entrant_id == entrant.entrant_id for item in self._state.entrants):
                raise TournamentError("entrant identifier is already registered")
            if any(item.account_id == entrant.account_id for item in self._state.entrants):
                raise TournamentError("account is already registered")
            candidate = self._state.model_copy(
                update={"entrants": (*self._state.entrants, entrant)}
            )
            return await self._save(candidate, actor_id, "register_entrant")

    async def verify_bot(self, entrant_id: str, *, actor_id: str) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.REGISTRATION_OPEN)
            found = False
            entrants = []
            for entrant in self._state.entrants:
                if entrant.entrant_id == entrant_id:
                    if entrant.kind is not EntryKind.BOT:
                        raise TournamentError("entrant is not a bot")
                    entrant = entrant.model_copy(update={"bot_verified": True})
                    found = True
                entrants.append(entrant)
            if not found:
                raise TournamentError("entrant does not exist")
            candidate = self._state.model_copy(update={"entrants": tuple(entrants)})
            return await self._save(candidate, actor_id, "verify_bot")

    async def seat_entrants(self, *, actor_id: str) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.REGISTRATION_OPEN)
            if not 2 <= len(self._state.entrants) <= self._state.config.max_players:
                raise TournamentError("tournament requires between 2 and max_players entrants")
            if any(
                entrant.kind is EntryKind.BOT and not entrant.bot_verified
                for entrant in self._state.entrants
            ):
                raise TournamentError("all bots must be verified before seating")
            tables = self._initial_tables()
            candidate = self._state.model_copy(
                update={"tables": tables, "status": TournamentStatus.SEATED}
            )
            return await self._save(candidate, actor_id, "seat_entrants")

    async def start(self, *, actor_id: str) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.SEATED)
            candidate = self._state.model_copy(update={"status": TournamentStatus.RUNNING})
            candidate = candidate.model_copy(update={"tables": self._start_ready_hands(candidate)})
            return await self._save(candidate, actor_id, "start_tournament")

    async def request_pause(self, *, actor_id: str) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.RUNNING)
            status = (
                TournamentStatus.PAUSE_REQUESTED
                if any(table.hand_in_progress for table in self._state.tables)
                else TournamentStatus.PAUSED
            )
            candidate = self._state.model_copy(update={"status": status})
            return await self._save(candidate, actor_id, "request_pause")

    async def resume(self, *, actor_id: str) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.PAUSED)
            candidate = self._state.model_copy(update={"status": TournamentStatus.RUNNING})
            candidate = self._begin_round_or_break(candidate)
            return await self._save(candidate, actor_id, "resume_tournament")

    async def tick(self, elapsed_seconds: int, *, actor_id: str = "clock") -> TournamentState:
        if elapsed_seconds < 0:
            raise ValueError("elapsed_seconds cannot be negative")
        async with self._lock:
            if self._state.status not in {TournamentStatus.RUNNING, TournamentStatus.BREAK}:
                return self._state
            candidate = self._advance_clock(self._state, elapsed_seconds)
            if candidate == self._state:
                return self._state
            return await self._save(candidate, actor_id, "advance_clock")

    async def advance_level(self, *, actor_id: str) -> TournamentState:
        async with self._lock:
            self._require_status(TournamentStatus.RUNNING)
            candidate = self._advance_clock(
                self._state.model_copy(update={"phase_remaining_seconds": 0}),
                0,
            )
            return await self._save(candidate, actor_id, "advance_level")

    async def record_hand_completed(
        self,
        table_id: str,
        stacks: Mapping[str, int],
        *,
        actor_id: str = "table-coordinator",
    ) -> TournamentState:
        async with self._lock:
            if self._state.status not in {
                TournamentStatus.RUNNING,
                TournamentStatus.PAUSE_REQUESTED,
            }:
                raise TournamentError("tournament is not accepting hand results")
            tables = list(self._state.tables)
            try:
                table_index = next(
                    i for i, table in enumerate(tables) if table.table_id == table_id
                )
            except StopIteration as exc:
                raise TournamentError("table does not exist") from exc
            table = tables[table_index]
            if not table.hand_in_progress:
                raise TournamentError("table has no hand in progress")
            expected = {player.entrant_id for player in table.players}
            if set(stacks) != expected:
                raise TournamentError("hand result must contain every table entrant exactly once")
            if any(
                isinstance(stack, bool) or not isinstance(stack, int) or stack < 0
                for stack in stacks.values()
            ):
                raise TournamentError("hand result stacks must be non-negative integers")
            if sum(stacks.values()) != sum(player.stack for player in table.players):
                raise TournamentError("hand result does not conserve chips")

            eliminated = [player for player in table.players if stacks[player.entrant_id] == 0]
            standings = self._elimination_standings(table, eliminated)
            remaining = tuple(
                player.model_copy(update={"stack": stacks[player.entrant_id]})
                for player in table.players
                if stacks[player.entrant_id] > 0
            )
            if remaining:
                button = table.button_seat
                if button not in {player.seat for player in remaining}:
                    button = clockwise_occupied(
                        (player.seat for player in remaining), table.button_seat
                    )[0]
                tables[table_index] = table.model_copy(
                    update={
                        "players": remaining,
                        "button_seat": button,
                        "hand_in_progress": False,
                        "start_of_hand_stacks": {},
                    }
                )
            else:
                tables.pop(table_index)

            candidate = self._state.model_copy(
                update={
                    "tables": tuple(tables),
                    "standings": (*self._state.standings, *standings),
                }
            )
            active = [player for item in candidate.tables for player in item.players]
            if len(active) == 1:
                winner = active[0]
                candidate = candidate.model_copy(
                    update={
                        "status": TournamentStatus.COMPLETED,
                        "standings": (
                            *candidate.standings,
                            Standing(
                                entrant_id=winner.entrant_id,
                                display_name=winner.display_name,
                                position=1,
                                start_of_hand_stack=winner.stack,
                            ),
                        ),
                        "tables": tuple(
                            item.model_copy(update={"hand_in_progress": False})
                            for item in candidate.tables
                        ),
                    }
                )
            elif not any(item.hand_in_progress for item in candidate.tables):
                if candidate.status is TournamentStatus.PAUSE_REQUESTED:
                    candidate = candidate.model_copy(update={"status": TournamentStatus.PAUSED})
                else:
                    candidate = self._begin_round_or_break(candidate)
            return await self._save(candidate, actor_id, "record_hand_completed")

    def hand_request(self, table_id: str, *, table_version: int = 0) -> StartHandRequest:
        table = self._find_table(table_id)
        if not table.hand_in_progress:
            raise TournamentError("table has no scheduled hand")
        level = self._state.config.level(table.hand_level_number)
        deck = list(_STANDARD_DECK)
        deterministic_rng(
            self._state.seed_hex,
            f"deck:{table.table_id}:{table.hand_number}",
        ).shuffle(deck)
        return StartHandRequest(
            tournament_id=self._state.tournament_id,
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
                    entrant_id=player.entrant_id,
                    display_name=player.display_name,
                    kind=player.kind,
                    stack=player.stack,
                )
                for player in table.players
            ),
            deck_order=tuple(deck),
        )

    async def dispatch_hand(
        self,
        table_id: str,
        coordinator: TableCoordinator,
    ) -> HandSnapshot:
        """Dispatch a scheduled hand through the authoritative table coordinator."""

        if coordinator.table_id != table_id:
            raise TournamentError("coordinator targets a different table")
        runtime = coordinator.state.snapshot
        table = self._find_table(table_id)
        if table.hand_number == 1:
            if runtime is not None:
                raise TournamentError("first hand cannot replace an initialized table")
            return await coordinator.start_table(self.hand_request(table_id))
        if runtime is None:
            raise TournamentError("next hand requires a restored table coordinator")
        request = self.hand_request(
            table_id,
            table_version=runtime.table_version + 1,
        )
        return await coordinator.start_next_hand(request)

    async def _save(
        self,
        candidate: TournamentState,
        actor_id: str,
        command: str,
    ) -> TournamentState:
        expected = self._state.revision
        candidate = candidate.model_copy(update={"revision": expected + 1})
        candidate = TournamentState.model_validate(candidate.model_dump(mode="python"))
        await self._store.save(
            candidate,
            expected_revision=expected,
            audit=AuditEntry(actor_id=actor_id, command=command),
        )
        self._state = candidate
        return candidate

    def _initial_tables(self) -> tuple[TournamentTable, ...]:
        entrants = list(self._state.entrants)
        rng = deterministic_rng(self._state.seed_hex, "initial-seating")
        rng.shuffle(entrants)
        table_count = math.ceil(len(entrants) / self._state.config.table_size)
        base, extra = divmod(len(entrants), table_count)
        tables = []
        cursor = 0
        for index in range(table_count):
            size = base + (1 if index < extra else 0)
            group = entrants[cursor : cursor + size]
            cursor += size
            players = tuple(
                TournamentPlayer(
                    entrant_id=entrant.entrant_id,
                    account_id=entrant.account_id,
                    display_name=entrant.display_name,
                    kind=entrant.kind,
                    seat=seat,
                    stack=self._state.config.starting_stack,
                )
                for seat, entrant in enumerate(group, start=1)
            )
            button = rng.choice([player.seat for player in players])
            tables.append(
                TournamentTable(
                    table_id=f"{self._state.tournament_id}-table-{index + 1}",
                    players=players,
                    button_seat=button,
                )
            )
        return tuple(tables)

    def _start_ready_hands(self, state: TournamentState) -> tuple[TournamentTable, ...]:
        started = []
        for table in state.tables:
            if table.hand_in_progress or len(table.players) < 2:
                started.append(table)
                continue
            button = table.button_seat if table.hand_number == 0 else next_button(table)
            started.append(
                table.model_copy(
                    update={
                        "hand_number": table.hand_number + 1,
                        "hand_level_number": state.level_number,
                        "button_seat": button,
                        "hand_in_progress": True,
                        "start_of_hand_stacks": {
                            player.entrant_id: player.stack for player in table.players
                        },
                    }
                )
            )
        return tuple(started)

    def _begin_round_or_break(self, state: TournamentState) -> TournamentState:
        tables, balance_counter = self._consolidate_and_balance(state)
        state = state.model_copy(
            update={"tables": tables, "balance_counter": balance_counter}
        )
        if state.break_pending:
            return state.model_copy(
                update={
                    "status": TournamentStatus.BREAK,
                    "phase_remaining_seconds": state.config.break_duration_seconds,
                    "break_pending": False,
                }
            )
        return state.model_copy(update={"tables": self._start_ready_hands(state)})

    def _advance_clock(self, state: TournamentState, elapsed_seconds: int) -> TournamentState:
        if state.break_pending:
            return state
        remaining_elapsed = elapsed_seconds
        candidate = state
        while remaining_elapsed >= candidate.phase_remaining_seconds:
            remaining_elapsed -= candidate.phase_remaining_seconds
            if candidate.status is TournamentStatus.BREAK:
                next_level = candidate.level_number + 1
                candidate = candidate.model_copy(
                    update={
                        "status": TournamentStatus.RUNNING,
                        "level_number": next_level,
                        "phase_remaining_seconds": candidate.config.level(
                            next_level
                        ).duration_seconds,
                    }
                )
                candidate = candidate.model_copy(
                    update={"tables": self._start_ready_hands(candidate)}
                )
                if candidate.phase_remaining_seconds == 0:
                    break
                continue

            if candidate.level_number % candidate.config.break_every_levels == 0:
                if any(table.hand_in_progress for table in candidate.tables):
                    return candidate.model_copy(
                        update={"phase_remaining_seconds": 0, "break_pending": True}
                    )
                candidate = candidate.model_copy(
                    update={
                        "status": TournamentStatus.BREAK,
                        "phase_remaining_seconds": candidate.config.break_duration_seconds,
                    }
                )
                if candidate.phase_remaining_seconds == 0:
                    continue
                continue

            next_level = candidate.level_number + 1
            candidate = candidate.model_copy(
                update={
                    "level_number": next_level,
                    "phase_remaining_seconds": candidate.config.level(
                        next_level
                    ).duration_seconds,
                }
            )
            if candidate.phase_remaining_seconds == 0:
                break
        if candidate.phase_remaining_seconds > 0:
            candidate = candidate.model_copy(
                update={
                    "phase_remaining_seconds": candidate.phase_remaining_seconds
                    - remaining_elapsed
                }
            )
        return candidate

    def _elimination_standings(
        self,
        table: TournamentTable,
        eliminated: list[TournamentPlayer],
    ) -> tuple[Standing, ...]:
        if not eliminated:
            return ()
        current_active = sum(len(item.players) for item in self._state.tables)
        survivors = current_active - len(eliminated)
        stacks = table.start_of_hand_stacks
        return tuple(
            Standing(
                entrant_id=player.entrant_id,
                display_name=player.display_name,
                position=survivors
                + 1
                + sum(
                    1
                    for other in eliminated
                    if stacks[other.entrant_id] > stacks[player.entrant_id]
                ),
                eliminated_hand_number=table.hand_number,
                start_of_hand_stack=stacks[player.entrant_id],
            )
            for player in sorted(
                eliminated,
                key=lambda item: (-stacks[item.entrant_id], item.entrant_id),
            )
        )

    def _consolidate_and_balance(
        self,
        state: TournamentState,
    ) -> tuple[tuple[TournamentTable, ...], int]:
        tables = list(state.tables)
        active_count = sum(len(table.players) for table in tables)
        required = math.ceil(active_count / state.config.table_size)
        counter = state.balance_counter

        while len(tables) > required:
            minimum = min(len(table.players) for table in tables)
            source = max(
                (table for table in tables if len(table.players) == minimum),
                key=table_sort_key,
            )
            tables.remove(source)
            movers = list(source.players)
            deterministic_rng(state.seed_hex, f"break-table:{counter}").shuffle(movers)
            counter += 1
            for mover in movers:
                minimum_target = min(len(table.players) for table in tables)
                targets = sorted(
                    (
                        table
                        for table in tables
                        if len(table.players) == minimum_target
                        and len(table.players) < state.config.table_size
                    ),
                    key=table_sort_key,
                )
                rng = deterministic_rng(state.seed_hex, f"break-destination:{counter}")
                target = targets[rng.randrange(len(targets))]
                counter += 1
                seat = worst_legal_vacancy(target)
                moved = mover.model_copy(update={"seat": seat})
                replacement = target.model_copy(update={"players": (*target.players, moved)})
                tables[tables.index(target)] = replacement

        while tables and max(map(lambda item: len(item.players), tables)) - min(
            map(lambda item: len(item.players), tables)
        ) > 1:
            donor = max(tables, key=lambda item: (len(item.players), table_sort_key(item)))
            receiver = min(tables, key=lambda item: (len(item.players), table_sort_key(item)))
            mover = next_big_blind_player(donor)
            remaining = tuple(player for player in donor.players if player != mover)
            donor_button = donor.button_seat
            if donor_button == mover.seat:
                donor_button = clockwise_occupied(
                    (player.seat for player in remaining), donor.button_seat
                )[0]
            donor_update = donor.model_copy(
                update={"players": remaining, "button_seat": donor_button}
            )
            moved = mover.model_copy(update={"seat": worst_legal_vacancy(receiver)})
            receiver_update = receiver.model_copy(
                update={"players": (*receiver.players, moved)}
            )
            tables[tables.index(donor)] = donor_update
            tables[tables.index(receiver)] = receiver_update
            counter += 1

        return tuple(sorted(tables, key=table_sort_key)), counter

    def _find_table(self, table_id: str) -> TournamentTable:
        try:
            return next(table for table in self._state.tables if table.table_id == table_id)
        except StopIteration as exc:
            raise TournamentError("table does not exist") from exc

    def _require_status(self, expected: TournamentStatus) -> None:
        if self._state.status is not expected:
            raise TournamentError(
                f"expected tournament status {expected.value}, found {self._state.status.value}"
            )
