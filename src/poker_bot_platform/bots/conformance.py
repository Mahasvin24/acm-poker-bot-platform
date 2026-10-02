from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from ipaddress import ip_network

from poker_bot_platform.bots.gateway import BotGateway
from poker_bot_platform.bots.models import (
    ActingPlayerState,
    BlindState,
    BotActionRequest,
    BotLegalAction,
    PublicSeat,
    PublicTableState,
)
from poker_bot_platform.bots.network import validate_bot_endpoint
from poker_bot_platform.bots.tokens import generate_verification_challenge
from poker_bot_platform.domain.models import ActionType, EntryKind, Street


def conformance_request(*, deadline_at: datetime | None = None) -> BotActionRequest:
    """Return the stable black-box request used by the conformance runner."""

    deadline = deadline_at or datetime.now(UTC) + timedelta(seconds=10)
    seats = (
        PublicSeat(
            seat=1,
            entrant_id="conformance-bot",
            display_name="Conformance Bot",
            kind=EntryKind.BOT,
            stack=19_800,
            committed_this_street=200,
            committed_this_hand=200,
            folded=False,
            all_in=False,
            eliminated=False,
        ),
        PublicSeat(
            seat=2,
            entrant_id="reference-opponent",
            display_name="Reference Opponent",
            kind=EntryKind.HUMAN,
            stack=19_800,
            committed_this_street=200,
            committed_this_hand=200,
            folded=False,
            all_in=False,
            eliminated=False,
        ),
    )
    return BotActionRequest(
        protocol="poker-bot.v1",
        tournament_id="conformance",
        table_id="table-1",
        hand_id="hand-1",
        decision_id="decision-1",
        table_version=1,
        deadline_at=deadline,
        table=PublicTableState(
            street=Street.FLOP,
            button_seat=1,
            blinds=BlindState(small_blind=100, big_blind=200, big_blind_ante=200),
            community_cards=("2c", "7d", "Jh"),
            seats=seats,
            pot=400,
        ),
        player=ActingPlayerState(
            seat=1,
            stack=19_800,
            committed_this_street=200,
            hole_cards=("As", "Kd"),
        ),
        legal_actions=(
            BotLegalAction(action=ActionType.CHECK),
            BotLegalAction(action=ActionType.RAISE, min_amount_to=400, max_amount_to=20_000),
        ),
    )


async def run_conformance(
    *,
    ip: str,
    port: int,
    token: str,
    participant_subnet: str,
) -> dict[str, object]:
    network = ip_network(participant_subnet, strict=False)
    endpoint = validate_bot_endpoint(
        ip,
        port,
        participant_subnet=network,
    )
    async with BotGateway(participant_subnet=network) as gateway:
        health = await gateway.health(endpoint)
        challenge = generate_verification_challenge()
        verification = await gateway.verify(endpoint, token, challenge)
        action = await gateway.request_action(endpoint, token, conformance_request())
    return {
        "health": health is not None,
        "verified": verification.verified,
        "verification_failure": (
            verification.failure_reason.value if verification.failure_reason else None
        ),
        "action_accepted": not action.used_fallback,
        "action": action.action.action.value,
        "action_failure": action.failure_reason.value if action.failure_reason else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a participant bot against protocol v1")
    parser.add_argument("--ip", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--token", required=True)
    parser.add_argument("--participant-subnet", default="192.168.0.0/16")
    args = parser.parse_args()
    report = asyncio.run(
        run_conformance(
            ip=args.ip,
            port=args.port,
            token=args.token,
            participant_subnet=args.participant_subnet,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if not all(report[key] for key in ("health", "verified", "action_accepted")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
