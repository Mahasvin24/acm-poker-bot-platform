from __future__ import annotations

from dataclasses import dataclass

from poker_bot_platform.bots import (
    BotEndpoint,
    BotGateway,
    action_request_from_snapshot,
)
from poker_bot_platform.coordinator import ActorDecisionFailure
from poker_bot_platform.domain import HandSnapshot, PendingDecision, PlayerAction


@dataclass(frozen=True, slots=True)
class BotActor:
    """Adapts the bot gateway to the coordinator's actor boundary.

    Gateway fallbacks are raised as structured failures so the coordinator is
    responsible for recording the automatic action and its failure reason.
    """

    gateway: BotGateway
    endpoint: BotEndpoint
    bearer_token: str

    async def __call__(
        self,
        pending: PendingDecision,
        snapshot: HandSnapshot,
    ) -> PlayerAction:
        request = action_request_from_snapshot(snapshot, pending)
        outcome = await self.gateway.request_action(
            self.endpoint,
            self.bearer_token,
            request,
        )
        if outcome.failure_reason is not None:
            raise ActorDecisionFailure(outcome.failure_reason)
        return outcome.action
