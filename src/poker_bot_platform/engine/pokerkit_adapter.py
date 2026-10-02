from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import version
from itertools import chain
from typing import Any

from pokerkit import (
    AntePosting,
    Automation,
    BetCollection,
    BlindOrStraddlePosting,
    CheckingOrCalling,
    CompletionBettingOrRaisingTo,
    Deck,
    NoLimitTexasHoldem,
    State,
)
from pokerkit import Card as PokerKitCard

from poker_bot_platform.domain import (
    ActionRecord,
    ActionType,
    DomainEvent,
    EngineTransition,
    HandSnapshot,
    LegalAction,
    PlayerAction,
    SeatState,
    SidePot,
    StartHandRequest,
    Street,
)


@dataclass(frozen=True)
class _RestoredHand:
    request: StartHandRequest
    state: State
    player_seats: tuple[int, ...]
    hole_cards_by_seat: dict[int, tuple[str, ...]]


class PokerKitEngine:
    """PokerKit-backed no-limit Hold'em implementation of the engine boundary.

    Only application-owned Pydantic models cross this boundary. A hand is
    restored by recreating it from its original request and replaying the
    immutable player action history against the supplied deck order.
    """

    adapter_version = f"pokerkit-{version('pokerkit')}-adapter-v1"

    _AUTOMATIONS = (
        Automation.BET_COLLECTION,
        Automation.CARD_BURNING,
        Automation.BOARD_DEALING,
        Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
        Automation.HAND_KILLING,
        Automation.CHIPS_PUSHING,
        Automation.CHIPS_PULLING,
    )

    def start_hand(self, request: StartHandRequest) -> EngineTransition:
        restored = self._create_hand(request)
        engine_state = self._engine_state(restored)
        snapshot = self._snapshot(
            restored,
            table_version=request.table_version,
            action_history=(),
            engine_state=engine_state,
        )
        events = [
            DomainEvent(
                event_type="hand_started",
                payload={
                    "hand_id": request.hand_id,
                    "acting_seat": snapshot.acting_seat,
                    "player_seats": list(restored.player_seats),
                },
            )
        ]
        events.extend(self._terminal_events(snapshot, request.seats))
        return EngineTransition(snapshot=snapshot, events=tuple(events))

    def apply_action(self, snapshot: HandSnapshot, action: PlayerAction) -> EngineTransition:
        if snapshot.adapter_version != self.adapter_version:
            raise ValueError("snapshot adapter version is incompatible")
        if snapshot.completed:
            raise ValueError("the hand is already complete")
        if action.table_version != snapshot.table_version:
            raise ValueError("stale table version")
        if action.seat != snapshot.acting_seat:
            raise ValueError("action is not for the acting seat")
        if any(record.decision_id == action.decision_id for record in snapshot.action_history):
            raise ValueError("decision has already been applied")

        restored = self._restore_state(snapshot)
        canonical = self._snapshot(
            restored,
            table_version=snapshot.table_version,
            action_history=snapshot.action_history,
            engine_state=snapshot.engine_state,
        )
        if canonical != snapshot:
            raise ValueError("snapshot does not match deterministic action replay")
        before_street = self._street(restored.state)
        self._apply_to_state(
            restored.state,
            restored.player_seats,
            action.action,
            action.seat,
            action.amount_to,
        )

        record = ActionRecord(
            sequence=len(snapshot.action_history) + 1,
            decision_id=action.decision_id,
            seat=action.seat,
            action=action.action,
            amount_to=action.amount_to,
        )
        updated = self._snapshot(
            restored,
            table_version=snapshot.table_version + 1,
            action_history=(*snapshot.action_history, record),
            engine_state=snapshot.engine_state,
        )
        events = [
            DomainEvent(
                event_type="action_applied",
                payload={
                    "seat": action.seat,
                    "action": action.action.value,
                    "amount_to": action.amount_to,
                    "table_version": updated.table_version,
                },
            )
        ]
        if not updated.completed and updated.street is not before_street:
            events.append(
                DomainEvent(
                    event_type="street_advanced",
                    payload={"street": updated.street.value},
                )
            )
        events.extend(self._terminal_events(updated, restored.request.seats))
        return EngineTransition(snapshot=updated, events=tuple(events))

    def restore(self, snapshot: HandSnapshot) -> HandSnapshot:
        if snapshot.adapter_version != self.adapter_version:
            raise ValueError("snapshot adapter version is incompatible")
        restored = self._restore_state(snapshot)
        rebuilt = self._snapshot(
            restored,
            table_version=snapshot.table_version,
            action_history=snapshot.action_history,
            engine_state=snapshot.engine_state,
        )
        if rebuilt != snapshot:
            raise ValueError("snapshot does not match deterministic action replay")
        return rebuilt

    def _create_hand(self, request: StartHandRequest) -> _RestoredHand:
        active_seats = tuple(
            seat for seat in request.seats if not seat.eliminated and seat.stack > 0
        )
        if not 2 <= len(active_seats) <= 6:
            raise ValueError("a hand requires between two and six funded seats")
        if len({seat.seat for seat in request.seats}) != len(request.seats):
            raise ValueError("seat numbers must be unique")
        if request.button_seat not in {seat.seat for seat in active_seats}:
            raise ValueError("button_seat must identify a funded seat")
        self._validate_deck(request.deck_order)

        # Index zero is the first occupied seat left of the button and the
        # button is last. This is PokerKit's natural order for 3+ players and
        # also makes its odd-chip remainder go to the first winner left of the
        # button. PokerKit itself applies the heads-up blind reversal.
        ordered = tuple(
            sorted(
                active_seats,
                key=lambda seat: (seat.seat - request.button_seat) % 6 or 6,
            )
        )
        player_count = len(ordered)
        starting_stacks = tuple(seat.stack for seat in ordered)
        raw_blinds = [0] * player_count
        raw_blinds[0] = request.small_blind
        raw_blinds[1] = request.big_blind

        # PokerKit processes antes before blinds. Reserve the BB first when
        # calculating the configured BBA so a short BB posts the blind before
        # contributing any remaining chips as ante, as required by house rules.
        bb_index = 0 if player_count == 2 else 1
        bb_stack = starting_stacks[bb_index]
        effective_bba = min(
            request.big_blind_ante,
            max(bb_stack - min(request.big_blind, bb_stack), 0),
        )
        raw_antes = [0] * player_count
        # PokerKit reverses positional values heads-up; raw slot 1 maps to the
        # BB for both heads-up and multi-way configurations in this ordering.
        raw_antes[1] = effective_bba

        state = NoLimitTexasHoldem.create_state(
            self._AUTOMATIONS,
            False,
            tuple(raw_antes),
            tuple(raw_blinds),
            request.big_blind,
            starting_stacks,
            player_count,
        )
        state.deck_cards = deque(PokerKitCard.parse(*request.deck_order))

        while state.can_post_ante():
            state.post_ante()
        while state.can_post_blind_or_straddle():
            state.post_blind_or_straddle()
        while state.can_deal_hole():
            state.deal_hole()

        player_seats = tuple(seat.seat for seat in ordered)
        # Derive the private record from the supplied deck itself. PokerKit may
        # automatically muck losing hands when every player is all-in from the
        # forced bets, before start_hand gets a chance to inspect hole_cards.
        dealt_cards = request.deck_order[: 2 * player_count]
        hole_cards_by_seat: dict[int, tuple[str, ...]] = {
            player_seats[index]: (dealt_cards[index], dealt_cards[index + player_count])
            for index in range(player_count)
        }
        return _RestoredHand(request, state, player_seats, hole_cards_by_seat)

    def _restore_state(self, snapshot: HandSnapshot) -> _RestoredHand:
        raw_request = snapshot.engine_state.get("start_request")
        if not isinstance(raw_request, dict):
            raise ValueError("snapshot is missing its start request")
        request = StartHandRequest.model_validate(raw_request)
        restored = self._create_hand(request)

        expected_player_seats = snapshot.engine_state.get("player_seats")
        if list(restored.player_seats) != expected_player_seats:
            raise ValueError("snapshot player ordering is incompatible")
        expected_hole_cards = snapshot.engine_state.get("hole_cards_by_seat")
        serialized_hole_cards = {
            str(seat): list(cards) for seat, cards in restored.hole_cards_by_seat.items()
        }
        if serialized_hole_cards != expected_hole_cards:
            raise ValueError("snapshot dealt cards are incompatible")

        for record in snapshot.action_history:
            self._apply_to_state(
                restored.state,
                restored.player_seats,
                record.action,
                record.seat,
                record.amount_to,
            )
        return restored

    def _apply_to_state(
        self,
        state: State,
        player_seats: tuple[int, ...],
        action: ActionType,
        seat: int,
        amount_to: int | None,
    ) -> None:
        actor_index = state.actor_index
        if actor_index is None or player_seats[actor_index] != seat:
            raise ValueError("action is not for the acting seat")

        if action is ActionType.FOLD:
            if amount_to is not None or not state.can_fold():
                raise ValueError("illegal fold")
            state.fold()
            return

        call_amount = state.checking_or_calling_amount
        if action is ActionType.CHECK:
            if amount_to is not None or call_amount != 0:
                raise ValueError("illegal check")
            state.check_or_call()
            return
        if action is ActionType.CALL:
            if amount_to is not None or call_amount is None or call_amount <= 0:
                raise ValueError("illegal call")
            state.check_or_call()
            return
        if action is ActionType.RAISE:
            if amount_to is None or not state.can_complete_bet_or_raise_to(amount_to):
                raise ValueError("illegal raise")
            state.complete_bet_or_raise_to(amount_to)
            return
        raise ValueError(f"unsupported action: {action}")

    def _snapshot(
        self,
        restored: _RestoredHand,
        *,
        table_version: int,
        action_history: tuple[ActionRecord, ...],
        engine_state: dict[str, Any],
    ) -> HandSnapshot:
        request = restored.request
        state = restored.state
        player_index_by_seat = {seat: index for index, seat in enumerate(restored.player_seats)}
        street_commitments, hand_commitments = self._commitments(state)
        folded_seats = {
            record.seat for record in action_history if record.action is ActionType.FOLD
        }
        completed = not state.status

        updated_seats = []
        for original in request.seats:
            index = player_index_by_seat.get(original.seat)
            if index is None:
                updated_seats.append(original)
                continue
            stack = state.stacks[index]
            folded = original.seat in folded_seats
            updated_seats.append(
                original.model_copy(
                    update={
                        "stack": stack,
                        "committed_this_street": street_commitments[index],
                        "committed_this_hand": hand_commitments[index],
                        "folded": folded,
                        "all_in": stack == 0 and not folded and not completed,
                        "eliminated": original.eliminated or (completed and stack == 0),
                        "hole_cards": restored.hole_cards_by_seat[original.seat],
                    }
                )
            )

        acting_seat = (
            None if state.actor_index is None else restored.player_seats[state.actor_index]
        )
        pots = tuple(state.pots)
        side_pots = tuple(
            SidePot(
                amount=pot.amount,
                eligible_seats=tuple(restored.player_seats[index] for index in pot.player_indices),
            )
            for pot in pots[1:]
        )
        return HandSnapshot(
            adapter_version=self.adapter_version,
            tournament_id=request.tournament_id,
            table_id=request.table_id,
            hand_id=request.hand_id,
            hand_number=request.hand_number,
            table_version=table_version,
            street=self._street(state),
            button_seat=request.button_seat,
            small_blind=request.small_blind,
            big_blind=request.big_blind,
            big_blind_ante=request.big_blind_ante,
            deck_order=request.deck_order,
            community_cards=tuple(repr(card) for card in chain.from_iterable(state.board_cards)),
            seats=tuple(updated_seats),
            pot=state.total_pot_amount,
            side_pots=side_pots,
            acting_seat=acting_seat,
            legal_actions=self._legal_actions(state),
            action_history=action_history,
            completed=completed,
            engine_state=engine_state,
        )

    def _legal_actions(self, state: State) -> tuple[LegalAction, ...]:
        if state.actor_index is None:
            return ()
        legal = []
        if state.can_fold():
            legal.append(LegalAction(action=ActionType.FOLD))
        call_amount = state.checking_or_calling_amount
        if call_amount == 0:
            legal.append(LegalAction(action=ActionType.CHECK))
        elif call_amount is not None:
            legal.append(LegalAction(action=ActionType.CALL, amount=call_amount))
        minimum = state.min_completion_betting_or_raising_to_amount
        maximum = state.max_completion_betting_or_raising_to_amount
        if minimum is not None and maximum is not None:
            legal.append(
                LegalAction(
                    action=ActionType.RAISE,
                    min_amount_to=minimum,
                    max_amount_to=maximum,
                )
            )
        return tuple(legal)

    def _terminal_events(
        self,
        snapshot: HandSnapshot,
        prior_seats: Iterable[SeatState],
    ) -> list[DomainEvent]:
        if not snapshot.completed:
            return []
        prior_seats = tuple(prior_seats)
        previous_stacks = {seat.seat: seat.stack for seat in prior_seats}
        payouts = []
        for seat in snapshot.seats:
            if seat.seat not in previous_stacks:
                continue
            net = seat.stack - previous_stacks[seat.seat]
            amount = net + seat.committed_this_hand
            if amount > 0:
                payouts.append(
                    {"seat": seat.seat, "amount": amount, "stack": seat.stack, "net": net}
                )
        previously_eliminated = {seat.seat for seat in prior_seats if seat.eliminated}
        eliminated_seats = [
            seat.seat
            for seat in snapshot.seats
            if seat.eliminated and seat.seat not in previously_eliminated
        ]
        return [
            DomainEvent(
                event_type="hand_completed",
                payload={"payouts": payouts, "eliminated_seats": eliminated_seats},
            )
        ]

    def _engine_state(self, restored: _RestoredHand) -> dict[str, Any]:
        return {
            "start_request": restored.request.model_dump(mode="json"),
            "player_seats": list(restored.player_seats),
            "hole_cards_by_seat": {
                str(seat): list(cards) for seat, cards in restored.hole_cards_by_seat.items()
            },
        }

    @staticmethod
    def _commitments(state: State) -> tuple[list[int], list[int]]:
        street = [0] * state.player_count
        hand = [0] * state.player_count
        for operation in state.operations:
            if isinstance(operation, AntePosting):
                hand[operation.player_index] += operation.amount
            elif isinstance(operation, (BlindOrStraddlePosting, CheckingOrCalling)):
                street[operation.player_index] += operation.amount
                hand[operation.player_index] += operation.amount
            elif isinstance(operation, CompletionBettingOrRaisingTo):
                delta = operation.amount - street[operation.player_index]
                street[operation.player_index] = operation.amount
                hand[operation.player_index] += delta
            elif isinstance(operation, BetCollection):
                street = [0] * state.player_count
        return street, hand

    @staticmethod
    def _street(state: State) -> Street:
        if not state.status:
            return Street.COMPLETE
        street_index = state.street_index
        if street_index == 0:
            return Street.PREFLOP
        if street_index == 1:
            return Street.FLOP
        if street_index == 2:
            return Street.TURN
        if street_index == 3:
            return Street.RIVER
        # With all showdown/payout operations automated, an active state must
        # always be on one of Hold'em's four betting streets.
        raise RuntimeError("PokerKit is in an unexpected non-betting state")

    @staticmethod
    def _validate_deck(deck_order: tuple[str, ...]) -> None:
        expected = {repr(card) for card in Deck.STANDARD}
        if len(deck_order) != len(expected) or set(deck_order) != expected:
            raise ValueError("deck_order must contain each standard card exactly once")
        # Pydantic validates card syntax; parsing here additionally guarantees
        # compatibility with the pinned PokerKit adapter.
        parsed = tuple(PokerKitCard.parse(*deck_order))
        if len(parsed) != len(expected):
            raise ValueError("deck_order is invalid")
