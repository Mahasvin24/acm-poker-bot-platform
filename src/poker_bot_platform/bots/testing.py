"""Bounded protocol checks using synthetic decisions, never live game state."""

from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

from pydantic import Field

from poker_bot_platform.bots.conformance import conformance_request
from poker_bot_platform.bots.gateway import BotGateway
from poker_bot_platform.bots.models import BotActionRequest, BotEndpoint, WireModel
from poker_bot_platform.bots.tokens import generate_verification_challenge
from poker_bot_platform.domain import ActionType, FailureReason


class BotTestCheck(WireModel):
    name: str
    description: str
    passed: bool
    elapsed_ms: int = Field(ge=0)
    message: str
    action: ActionType | None = None
    amount_to: int | None = None


class BotTestReport(WireModel):
    passed: bool
    checks: tuple[BotTestCheck, ...]


SCENARIOS = (
    ("Check or raise", "Check, or raise to 200–19,800 on the flop.", 19_800, 0, 200, 19_800),
    ("Facing a bet", "Fold, call 600, or raise to 1,200–19,800.", 19_800, 600, 1_200, 19_800),
    (
        "Short-stack call",
        "Fold or call all-in for 300 against a 600 bet; no raise.",
        300,
        600,
        None,
        None,
    ),
    (
        "Short all-in raise",
        "Fold, call 600, or make a short all-in raise to exactly 900.",
        900,
        600,
        900,
        900,
    ),
)

_FAILURES = {
    FailureReason.TIMEOUT: "No valid response within the 3-second deadline.",
    FailureReason.CONNECTION: "Could not connect to the registered LAN endpoint.",
    FailureReason.HTTP_STATUS: "Bot returned a non-success HTTP status. Check its token and logs.",
    FailureReason.CONTENT_TYPE: "Response must use Content-Type: application/json.",
    FailureReason.OVERSIZED: "Request or response exceeded the protocol size limit.",
    FailureReason.MALFORMED_JSON: "Response was invalid JSON or contained duplicate keys.",
    FailureReason.SCHEMA: "Response did not match poker-bot.v1. Check fields, types, and protocol.",
    FailureReason.STALE: "Response did not echo the current identifiers or verification challenge.",
    FailureReason.ILLEGAL_ACTION: "Action was illegal or the raise was out of bounds.",
}


def failure_message(reason: FailureReason | None) -> str:
    return (
        _FAILURES.get(reason, "Protocol check failed.")
        if reason is not None
        else "Protocol check failed."
    )


def decision_request(index: int, run_id: str) -> BotActionRequest:
    """Build each request at dispatch so earlier checks cannot consume its deadline."""
    _, _, stack, bet, minimum, maximum = SCENARIOS[index]
    raw = conformance_request(deadline_at=datetime.now(UTC) + timedelta(seconds=3)).model_dump()
    raw.update(
        tournament_id=f"bot-test-{run_id}",
        hand_id=f"scenario-{index + 1}",
        decision_id=str(uuid4()),
    )
    raw["player"].update(stack=stack, committed_this_street=0)
    raw["table"]["seats"][0].update(stack=stack, committed_this_street=0)
    raw["table"]["seats"][1].update(
        stack=19_600 - bet, committed_this_street=bet, committed_this_hand=400 + bet
    )
    raw["table"]["pot"] = 600 + bet
    legal: list[dict[str, object]] = (
        [{"action": "check"}]
        if bet == 0
        else [{"action": "fold"}, {"action": "call", "amount": min(stack, bet)}]
    )
    if minimum is not None:
        legal.append({"action": "raise", "min_amount_to": minimum, "max_amount_to": maximum})
    raw["legal_actions"] = legal
    return BotActionRequest.model_validate(raw)


async def run_bot_tests(gateway: BotGateway, endpoint: BotEndpoint, token: str) -> BotTestReport:
    checks: list[BotTestCheck] = []
    started = perf_counter()
    healthy = await gateway.health(endpoint) is not None
    checks.append(
        BotTestCheck(
            name="Health",
            description="GET /v1/health must report poker-bot.v1 and ready.",
            passed=healthy,
            elapsed_ms=round((perf_counter() - started) * 1000),
            message="Ready."
            if healthy
            else "Health check failed. Check reachability, JSON, and ready status.",
        )
    )
    started = perf_counter()
    verification = await gateway.verify(endpoint, token, generate_verification_challenge())
    checks.append(
        BotTestCheck(
            name="Authentication",
            description="POST /v1/verify must authenticate and echo the challenge.",
            passed=verification.verified,
            elapsed_ms=round((perf_counter() - started) * 1000),
            message="Challenge accepted."
            if verification.verified
            else failure_message(verification.failure_reason),
        )
    )
    run_id = uuid4().hex
    for index, (name, description, *_rest) in enumerate(SCENARIOS):
        request = decision_request(index, run_id)
        started = perf_counter()
        outcome = await gateway.request_action(endpoint, token, request)
        checks.append(
            BotTestCheck(
                name=name,
                description=description,
                passed=not outcome.used_fallback,
                elapsed_ms=round((perf_counter() - started) * 1000),
                message=failure_message(outcome.failure_reason)
                if outcome.used_fallback
                else "Legal action accepted.",
                action=None if outcome.used_fallback else outcome.action.action,
                amount_to=None if outcome.used_fallback else outcome.action.amount_to,
            )
        )
    return BotTestReport(passed=all(check.passed for check in checks), checks=tuple(checks))
