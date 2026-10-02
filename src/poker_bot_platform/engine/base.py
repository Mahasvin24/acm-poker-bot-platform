from __future__ import annotations

from typing import Protocol

from poker_bot_platform.domain import EngineTransition, HandSnapshot, PlayerAction, StartHandRequest


class PokerEngine(Protocol):
    """Application boundary around a poker rules implementation."""

    @property
    def adapter_version(self) -> str: ...

    def start_hand(self, request: StartHandRequest) -> EngineTransition: ...

    def apply_action(self, snapshot: HandSnapshot, action: PlayerAction) -> EngineTransition: ...

    def restore(self, snapshot: HandSnapshot) -> HandSnapshot: ...
