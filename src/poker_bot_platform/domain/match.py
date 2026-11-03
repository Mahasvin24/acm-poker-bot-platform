from __future__ import annotations

from pydantic import Field, model_validator

from poker_bot_platform.domain.models import ContractModel

BOT_ACTION_TIMEOUT_MS = 3_000
BOT_CONNECT_TIMEOUT_MS = 500


class BlindLevel(ContractModel):
    small_blind: int = Field(gt=0)
    big_blind: int = Field(gt=0)
    big_blind_ante: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_blinds(self) -> BlindLevel:
        if self.small_blind >= self.big_blind:
            raise ValueError("small blind must be less than big blind")
        if self.big_blind_ante not in {0, self.big_blind}:
            raise ValueError("the big-blind ante must be zero or equal to the big blind")
        return self


# Big blinds of the smooth WSOP Circuit progression used when blinds escalate.
# Each level scales the match's opening blinds by the ratio to the first entry.
_ESCALATION_BIG_BLINDS = (
    200, 300, 400, 500, 600, 800, 1_000, 1_200, 1_500, 2_000, 2_500, 3_000, 4_000, 5_000,
    6_000, 8_000, 10_000, 12_000, 15_000, 20_000, 25_000, 30_000, 40_000, 50_000, 60_000,
    80_000, 100_000, 120_000, 150_000,
)  # fmt: skip


class MatchConfig(ContractModel):
    max_seats: int = Field(default=6, ge=2, le=6)
    starting_stack: int = Field(default=20_000, gt=0, le=10_000_000)
    small_blind: int = Field(default=100, gt=0)
    big_blind: int = Field(default=200, gt=0)
    big_blind_ante: bool = False
    human_action_timeout_ms: int = Field(default=30_000, ge=5_000, le=300_000)
    blind_increase_minutes: int | None = Field(default=None, ge=1, le=120)

    @model_validator(mode="after")
    def validate_blinds(self) -> MatchConfig:
        if self.small_blind >= self.big_blind:
            raise ValueError("small blind must be less than big blind")
        if self.big_blind * 2 > self.starting_stack:
            raise ValueError("starting stack must cover at least two big blinds")
        return self

    @property
    def escalates(self) -> bool:
        return self.blind_increase_minutes is not None

    @property
    def level_seconds(self) -> int | None:
        if self.blind_increase_minutes is None:
            return None
        return self.blind_increase_minutes * 60

    def level(self, one_based_number: int) -> BlindLevel:
        if one_based_number < 1:
            raise ValueError("level numbers are one-based")
        if not self.escalates:
            one_based_number = 1
        schedule = _ESCALATION_BIG_BLINDS
        index = min(one_based_number, len(schedule)) - 1
        doublings = max(0, one_based_number - len(schedule))
        factor_numerator = schedule[index] * 2**doublings
        big_blind = max(1, self.big_blind * factor_numerator // schedule[0])
        small_blind = max(1, self.small_blind * factor_numerator // schedule[0])
        if small_blind >= big_blind:
            small_blind = max(1, big_blind // 2)
        return BlindLevel(
            small_blind=small_blind,
            big_blind=big_blind,
            big_blind_ante=big_blind if self.big_blind_ante else 0,
        )
