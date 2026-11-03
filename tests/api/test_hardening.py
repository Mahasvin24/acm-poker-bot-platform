from __future__ import annotations

import pytest
from pydantic import ValidationError

from poker_bot_platform.api.rate_limit import RateLimitExceeded, SlidingWindowLimiter
from poker_bot_platform.config import Settings
from poker_bot_platform.integration.demo_match import DemoMatchSessions


@pytest.mark.parametrize(
    "secret",
    [
        "development-only-change-before-event",
        "replace-with-at-least-32-random-characters",
        "x" * 40,
    ],
)
def test_settings_reject_placeholder_and_low_entropy_secrets(secret: str) -> None:
    with pytest.raises(ValidationError, match="POKER_SECRET_KEY"):
        Settings(secret_key=secret, _env_file=None)  # type: ignore[call-arg]


def test_settings_accept_random_secret() -> None:
    settings = Settings(
        secret_key="3f9c1a7e5b2d8046c9e1f7a3b5d20e84",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.secret_key.get_secret_value().startswith("3f9c")


def test_limiter_blocks_after_max_attempts_and_recovers_after_window() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(max_attempts=2, window_seconds=10, clock=lambda: now[0])

    limiter.record("player@example.com")
    limiter.record("player@example.com")
    with pytest.raises(RateLimitExceeded) as raised:
        limiter.check("player@example.com")
    assert raised.value.retry_after_seconds == 10

    limiter.check("someone-else@example.com")
    now[0] = 10.5
    limiter.check("player@example.com")


def test_limiter_reset_clears_failures() -> None:
    limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=60)
    limiter.record("key")
    limiter.reset("key")
    limiter.check("key")


async def test_demo_sessions_are_isolated_per_browser() -> None:
    sessions = DemoMatchSessions()
    try:
        first = await sessions.get("a" * 32)
        second = await sessions.get("b" * 32)
        assert first is not second
        assert first is await sessions.get("a" * 32)

        started = await first.start()
        assert started.status == "active"
        assert (await second.current()).status == "idle"
    finally:
        await sessions.aclose()


async def test_demo_sessions_evict_the_oldest_when_full() -> None:
    sessions = DemoMatchSessions(max_sessions=1)
    try:
        first = await sessions.get("a" * 32)
        await sessions.get("b" * 32)
        assert await sessions.get("a" * 32) is not first
    finally:
        await sessions.aclose()
