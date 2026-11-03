from __future__ import annotations

from poker_bot_platform.domain import FailureReason

_EXPLANATIONS: dict[FailureReason, str] = {
    FailureReason.TIMEOUT: (
        "Your bot did not answer within 3 seconds. Check that it is running and "
        "listening on the registered address and port."
    ),
    FailureReason.CONNECTION: (
        "The platform could not connect to your bot. Check the IP address and port, "
        "that the bot process is running, and that your firewall allows the port."
    ),
    FailureReason.HTTP_STATUS: (
        "Your bot answered with a non-2xx HTTP status. A 401 usually means the bearer "
        "token in your bot does not match the one shown when you saved the endpoint."
    ),
    FailureReason.CONTENT_TYPE: "Your bot must respond with Content-Type: application/json.",
    FailureReason.OVERSIZED: "Your bot's response was larger than the 4 KiB limit.",
    FailureReason.MALFORMED_JSON: (
        "Your bot's response was not valid JSON, or it contained duplicate keys."
    ),
    FailureReason.SCHEMA: (
        "Your bot's JSON did not match the protocol: check the protocol version, field "
        "names and types, and that there are no extra fields."
    ),
    FailureReason.STALE: (
        "Your bot echoed different identifiers than the request (challenge, match, "
        "hand, decision, or table version)."
    ),
    FailureReason.ILLEGAL_ACTION: (
        "Your bot chose an action that was not in legal_actions, or a raise outside "
        "min_amount_to and max_amount_to."
    ),
    FailureReason.RESTART_RECOVERY: (
        "The server restarted while waiting for this decision, so it was resolved automatically."
    ),
}


def explain_failure(reason: FailureReason | None) -> str:
    if reason is None:
        return "Verification failed for an unknown reason."
    return _EXPLANATIONS.get(reason, f"Verification failed: {reason.value.replace('_', ' ')}.")
