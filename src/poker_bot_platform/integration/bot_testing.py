from __future__ import annotations

import asyncio

from poker_bot_platform.auth.repository import AuthConflictError
from poker_bot_platform.auth.service import EntrantService
from poker_bot_platform.bots import BotGateway
from poker_bot_platform.bots.network import validate_bot_endpoint
from poker_bot_platform.bots.testing import BotTestReport, run_bot_tests
from poker_bot_platform.domain import EntryKind, TournamentStatus
from poker_bot_platform.integration.services import TournamentRegistry
from poker_bot_platform.tournament import TournamentError

SUITE_TIMEOUT_SECONDS = 20


class BotTestBusyError(RuntimeError):
    pass


class BotTestingService:
    def __init__(
        self, accounts: EntrantService, tournaments: TournamentRegistry, gateway: BotGateway
    ) -> None:
        self._accounts = accounts
        self._tournaments = tournaments
        self._gateway = gateway
        self._running: set[tuple[str, str]] = set()

    async def run(self, account_id: str, tournament_id: str) -> BotTestReport:
        key = (account_id, tournament_id)
        if key in self._running or len(self._running) >= 2:
            raise BotTestBusyError("bot testing is busy; try again shortly")
        self._running.add(key)
        try:
            async with asyncio.timeout(SUITE_TIMEOUT_SECONDS):
                tournament = await self._tournaments.get(tournament_id)
                async with tournament.registration_check():
                    entrant = await self._accounts.current(account_id, tournament_id)
                    if entrant.kind is not EntryKind.BOT:
                        raise AuthConflictError("only bot entrants can run bot tests")
                    if (
                        not entrant.bot_ip
                        or entrant.bot_port is None
                        or entrant.bot_token_ciphertext is None
                    ):
                        raise AuthConflictError("configure your bot endpoint before testing")
                    endpoint = validate_bot_endpoint(
                        entrant.bot_ip,
                        entrant.bot_port,
                        participant_subnet=self._accounts.participant_subnet,
                        blocked_ips=self._accounts.blocked_ips,
                    )
                    endpoint_key = (str(endpoint.ip), endpoint.port)
                    async with self._tournaments.endpoints.reserve([endpoint_key]):
                        # Admission holds the same endpoint locks until its state
                        # commit. Either this scan sees that commit, or admission
                        # waits until the entire test suite releases the endpoint.
                        for active_id in await self._tournaments.discover_active_tournaments():
                            if active_id == tournament_id:
                                continue
                            active = (await self._tournaments.get(active_id)).state
                            if active.status in {
                                TournamentStatus.SEATED,
                                TournamentStatus.RUNNING,
                                TournamentStatus.PAUSE_REQUESTED,
                                TournamentStatus.PAUSED,
                                TournamentStatus.BREAK,
                            }:
                                for player in active.entrants:
                                    configured = await self._accounts.repository.get_entrant_by_id(
                                        player.entrant_id
                                    )
                                    if (
                                        configured is not None
                                        and (configured.bot_ip, configured.bot_port) == endpoint_key
                                    ):
                                        raise AuthConflictError(
                                            "endpoint is assigned to another live tournament"
                                        )
                        token = self._accounts.token_store.decrypt(entrant.bot_token_ciphertext)
                        return await run_bot_tests(self._gateway, endpoint, token)
        except TournamentError as exc:
            raise AuthConflictError(
                "bot testing is only available while registration is open"
            ) from exc
        finally:
            self._running.remove(key)
