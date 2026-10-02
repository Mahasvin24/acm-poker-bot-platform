from __future__ import annotations

from pydantic import Field, model_validator

from poker_bot_platform.domain.models import ContractModel


class BlindLevel(ContractModel):
    small_blind: int = Field(gt=0)
    big_blind: int = Field(gt=0)
    big_blind_ante: int = Field(ge=0)
    duration_seconds: int = Field(default=900, gt=0)

    @model_validator(mode="after")
    def validate_blinds(self) -> BlindLevel:
        if self.small_blind >= self.big_blind:
            raise ValueError("small blind must be less than big blind")
        return self


_DEFAULT_BLINDS = (
    (100, 200),
    (100, 300),
    (200, 400),
    (300, 600),
    (400, 800),
    (500, 1_000),
    (600, 1_200),
    (1_000, 1_500),
    (1_000, 2_000),
    (1_500, 3_000),
    (2_000, 4_000),
    (3_000, 6_000),
    (4_000, 8_000),
    (5_000, 10_000),
    (10_000, 20_000),
    (15_000, 30_000),
    (20_000, 40_000),
    (30_000, 60_000),
    (40_000, 80_000),
    (50_000, 100_000),
)


def default_blind_levels() -> tuple[BlindLevel, ...]:
    return tuple(
        BlindLevel(small_blind=sb, big_blind=bb, big_blind_ante=bb) for sb, bb in _DEFAULT_BLINDS
    )


class TournamentConfig(ContractModel):
    max_players: int = Field(default=36, ge=2, le=36)
    table_size: int = Field(default=6, ge=2, le=6)
    starting_stack: int = Field(default=20_000, gt=0)
    human_action_timeout_ms: int = Field(default=30_000, ge=1_000)
    # Bot timing is part of the public v1 wire contract, not a tournament knob.
    bot_action_timeout_ms: int = Field(default=3_000, ge=3_000, le=3_000)
    bot_connect_timeout_ms: int = Field(default=500, ge=500, le=500)
    break_every_levels: int = Field(default=3, gt=0)
    break_duration_seconds: int = Field(default=600, ge=0)
    levels: tuple[BlindLevel, ...] = Field(default_factory=default_blind_levels)

    @model_validator(mode="after")
    def validate_fixed_v1_limits(self) -> TournamentConfig:
        if self.table_size != 6:
            raise ValueError("v1 tournaments are six-handed")
        if not self.levels:
            raise ValueError("at least one blind level is required")
        return self

    def level(self, one_based_number: int) -> BlindLevel:
        if one_based_number < 1:
            raise ValueError("level numbers are one-based")
        if one_based_number <= len(self.levels):
            return self.levels[one_based_number - 1]
        previous = self.levels[-1]
        doublings = one_based_number - len(self.levels)
        factor = 2**doublings
        return BlindLevel(
            small_blind=previous.small_blind * factor,
            big_blind=previous.big_blind * factor,
            big_blind_ante=previous.big_blind_ante * factor,
            duration_seconds=previous.duration_seconds,
        )
