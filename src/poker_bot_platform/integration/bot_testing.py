from __future__ import annotations

import asyncio

from poker_bot_platform.bots import BotGateway
from poker_bot_platform.bots.testing import BotTestReport, run_bot_tests
from poker_bot_platform.integration.matches import MatchService

SUITE_TIMEOUT_SECONDS = 35


class BotTestBusyError(RuntimeError):
    pass


class BotTestingService:
    """Bounded owner-only protocol tests, isolated from live match endpoints."""

    def __init__(self, matches: MatchService, gateway: BotGateway) -> None:
        self._matches = matches
        self._gateway = gateway
        self._running: set[str] = set()

    async def run(self, account_id: str, bot_id: str) -> BotTestReport:
        if bot_id in self._running or len(self._running) >= 2:
            raise BotTestBusyError("bot testing is busy; try again shortly")
        self._running.add(bot_id)
        try:
            async with asyncio.timeout(SUITE_TIMEOUT_SECONDS):
                async with self._matches.bot_setup(account_id, bot_id) as profile:
                    endpoint = self._matches.bot_endpoint(profile)
                    token = self._matches.bot_token(profile)
                    return await run_bot_tests(self._gateway, endpoint, token)
        finally:
            self._running.remove(bot_id)
