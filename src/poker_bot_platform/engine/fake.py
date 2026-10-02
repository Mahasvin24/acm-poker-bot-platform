from __future__ import annotations

from poker_bot_platform.domain import (
    ActionRecord,
    ActionType,
    DomainEvent,
    EngineTransition,
    HandSnapshot,
    LegalAction,
    PlayerAction,
    StartHandRequest,
    Street,
)


class FakePokerEngine:
    """Small contract test double; it is not poker logic."""

    adapter_version = "fake-v1"

    def start_hand(self, request: StartHandRequest) -> EngineTransition:
        active = tuple(seat for seat in request.seats if not seat.eliminated and seat.stack > 0)
        if len(active) < 2:
            raise ValueError("at least two funded seats are required")
        acting = active[0].seat
        snapshot = HandSnapshot(
            adapter_version=self.adapter_version,
            tournament_id=request.tournament_id,
            table_id=request.table_id,
            hand_id=request.hand_id,
            hand_number=request.hand_number,
            table_version=request.table_version,
            street=Street.PREFLOP,
            button_seat=request.button_seat,
            small_blind=request.small_blind,
            big_blind=request.big_blind,
            big_blind_ante=request.big_blind_ante,
            deck_order=request.deck_order,
            seats=request.seats,
            acting_seat=acting,
            legal_actions=(
                LegalAction(action=ActionType.FOLD),
                LegalAction(action=ActionType.CHECK),
            ),
        )
        return EngineTransition(
            snapshot=snapshot,
            events=(DomainEvent(event_type="hand_started", payload={"acting_seat": acting}),),
        )

    def apply_action(self, snapshot: HandSnapshot, action: PlayerAction) -> EngineTransition:
        if snapshot.completed or snapshot.acting_seat != action.seat:
            raise ValueError("action is not for the acting seat")
        if action.table_version != snapshot.table_version:
            raise ValueError("stale table version")
        allowed = {candidate.action for candidate in snapshot.legal_actions}
        if action.action not in allowed:
            raise ValueError("illegal action")
        record = ActionRecord(
            sequence=len(snapshot.action_history) + 1,
            decision_id=action.decision_id,
            seat=action.seat,
            action=action.action,
            amount_to=action.amount_to,
        )
        updated = snapshot.model_copy(
            update={
                "table_version": snapshot.table_version + 1,
                "street": Street.COMPLETE,
                "acting_seat": None,
                "legal_actions": (),
                "action_history": (*snapshot.action_history, record),
                "completed": True,
            }
        )
        return EngineTransition(
            snapshot=updated,
            events=(
                DomainEvent(
                    event_type="action_applied",
                    payload={"seat": action.seat, "action": action.action.value},
                ),
            ),
        )

    def restore(self, snapshot: HandSnapshot) -> HandSnapshot:
        if snapshot.adapter_version != self.adapter_version:
            raise ValueError("snapshot adapter version is incompatible")
        return snapshot
