from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    ip_address,
)

from poker_bot_platform.bots.models import BotEndpoint

IPAddress = IPv4Address | IPv6Address
IPNetwork = IPv4Network | IPv6Network


class BotPath(StrEnum):
    HEALTH = "/v1/health"
    VERIFY = "/v1/verify"
    ACTION = "/v1/action"


def validate_bot_endpoint(
    ip_text: str,
    port: int,
    *,
    participant_subnet: IPNetwork,
    blocked_ips: Iterable[str | IPAddress] = (),
) -> BotEndpoint:
    """Validate a numeric participant address against the event allowlist."""

    if not isinstance(ip_text, str) or not ip_text or ip_text != ip_text.strip():
        raise ValueError("bot IP must be a numeric address")
    if "%" in ip_text:
        raise ValueError("scoped IPv6 addresses are not supported")
    try:
        address = ip_address(ip_text)
    except ValueError as exc:
        raise ValueError("bot IP must be a numeric address") from exc

    if address.version != participant_subnet.version or address not in participant_subnet:
        raise ValueError("bot IP is outside the participant subnet")
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        raise ValueError("bot IP is not an eligible participant address")
    if (
        address == participant_subnet.network_address
        or address == participant_subnet.broadcast_address
    ):
        raise ValueError("bot IP is a subnet infrastructure address")

    blocked = {
        item if isinstance(item, (IPv4Address, IPv6Address)) else ip_address(item)
        for item in blocked_ips
    }
    if address in blocked:
        raise ValueError("bot IP is reserved for tournament infrastructure")
    return BotEndpoint(ip=address, port=port)


def endpoint_url(endpoint: BotEndpoint, path: BotPath) -> str:
    """Construct a URL from validated fields and a platform-owned fixed path."""

    host = f"[{endpoint.ip}]" if endpoint.ip.version == 6 else str(endpoint.ip)
    return f"http://{host}:{endpoint.port}{path.value}"
