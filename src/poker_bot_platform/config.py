from __future__ import annotations

from ipaddress import IPv4Network, IPv6Network, ip_network

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. V1 is intentionally a single-process application."""

    model_config = SettingsConfigDict(env_prefix="POKER_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://poker:poker@localhost:5432/poker"
    secret_key: SecretStr = Field(min_length=32)
    participant_subnet: IPv4Network | IPv6Network = ip_network("192.168.0.0/16")
    blocked_ips: tuple[str, ...] = ()
    log_level: str = "INFO"
    worker_count: int = 1

    @field_validator("participant_subnet", mode="before")
    @classmethod
    def parse_network(cls, value: object) -> IPv4Network | IPv6Network:
        if isinstance(value, (IPv4Network, IPv6Network)):
            return value
        return ip_network(str(value), strict=False)

    @field_validator("blocked_ips", mode="before")
    @classmethod
    def parse_blocked_ips(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        if isinstance(value, (list, tuple, set)):
            return tuple(str(part) for part in value)
        if value is None:
            return ()
        raise ValueError("blocked_ips must be a comma-separated string or sequence")

    @field_validator("worker_count")
    @classmethod
    def single_worker_only(cls, value: int) -> int:
        if value != 1:
            raise ValueError("v1 requires exactly one application worker")
        return value
