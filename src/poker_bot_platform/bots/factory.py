from __future__ import annotations

from poker_bot_platform.bots.models import (
    BOT_PROTOCOL_VERSION,
    ActingPlayerState,
    BlindState,
    BotActionRequest,
    BotLegalAction,
    FinalStack,
    MatchContext,
    PotAward,
    PreviousHand,
    PublicAction,
    PublicSeat,
    PublicSidePot,
    PublicTableState,
    ShownHand,
)
from poker_bot_platform.domain.models import HandSnapshot, PendingDecision


def previous_hand_from_snapshot(snapshot: HandSnapshot) -> PreviousHand | None:
    """Summarize a completed hand using only information that became public."""

    if not snapshot.completed:
        return None
    awards = tuple(
        PotAward(seat=raw["seat"], amount=raw["amount"])
        for raw in snapshot.engine_state.get("pot_awards", [])
        if isinstance(raw, dict)
        and isinstance(raw.get("seat"), int)
        and isinstance(raw.get("amount"), int)
        and raw["amount"] > 0
    )
    return PreviousHand(
        hand_id=snapshot.hand_id,
        hand_number=snapshot.hand_number,
        community_cards=snapshot.community_cards,
        shown_hands=tuple(
            ShownHand(seat=seat.seat, hole_cards=seat.public_hole_cards)
            for seat in snapshot.seats
            if seat.public_hole_cards
        ),
        awards=awards,
        final_stacks=tuple(
            FinalStack(seat=seat.seat, entrant_id=seat.entrant_id, stack=seat.stack)
            for seat in snapshot.seats
        ),
    )


def action_request_from_snapshot(
    snapshot: HandSnapshot,
    pending: PendingDecision,
    *,
    match: MatchContext | None = None,
    previous_hand: PreviousHand | None = None,
) -> BotActionRequest:
    """Build the bot view without exposing another player or recovery-only state."""

    if snapshot.table_id != pending.table_id or snapshot.hand_id != pending.hand_id:
        raise ValueError("pending decision does not belong to this snapshot")
    if snapshot.table_version != pending.table_version:
        raise ValueError("pending decision version does not match the snapshot")
    if snapshot.acting_seat != pending.seat:
        raise ValueError("pending decision seat is not the snapshot's acting seat")
    if pending.legal_actions != snapshot.legal_actions:
        raise ValueError("pending legal actions do not match the engine snapshot")
    acting = next((seat for seat in snapshot.seats if seat.seat == pending.seat), None)
    if acting is None:
        raise ValueError("acting seat is missing from the snapshot")

    public_seats = tuple(
        PublicSeat(
            seat=seat.seat,
            entrant_id=seat.entrant_id,
            display_name=seat.display_name,
            kind=seat.kind,
            stack=seat.stack,
            committed_this_street=seat.committed_this_street,
            committed_this_hand=seat.committed_this_hand,
            folded=seat.folded,
            all_in=seat.all_in,
            eliminated=seat.eliminated,
        )
        for seat in snapshot.seats
    )
    public_history = tuple(
        PublicAction(
            sequence=record.sequence,
            seat=record.seat,
            street=record.street or snapshot.street,
            action=record.action,
            amount_to=record.amount_to,
            automatic=record.automatic,
        )
        for record in snapshot.action_history
    )
    return BotActionRequest(
        protocol=BOT_PROTOCOL_VERSION,
        match_id=snapshot.match_id,
        table_id=snapshot.table_id,
        hand_id=snapshot.hand_id,
        decision_id=pending.decision_id,
        table_version=snapshot.table_version,
        deadline_at=pending.deadline_at,
        table=PublicTableState(
            street=snapshot.street,
            button_seat=snapshot.button_seat,
            blinds=BlindState(
                small_blind=snapshot.small_blind,
                big_blind=snapshot.big_blind,
                big_blind_ante=snapshot.big_blind_ante,
            ),
            community_cards=snapshot.community_cards,
            seats=public_seats,
            pot=snapshot.pot,
            side_pots=tuple(PublicSidePot.from_domain(pot) for pot in snapshot.side_pots),
            action_history=public_history,
        ),
        player=ActingPlayerState(
            seat=acting.seat,
            stack=acting.stack,
            committed_this_street=acting.committed_this_street,
            hole_cards=acting.hole_cards,
        ),
        legal_actions=tuple(
            BotLegalAction.model_validate(action.model_dump()) for action in pending.legal_actions
        ),
        match=match,
        previous_hand=previous_hand,
    )
