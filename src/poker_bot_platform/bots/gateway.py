from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Network, IPv6Network
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from poker_bot_platform.bots.models import (
    BotActionRequest,
    BotActionResponse,
    BotEndpoint,
    BotLegalAction,
    HealthResponse,
    VerifyRequest,
    VerifyResponse,
)
from poker_bot_platform.bots.network import BotPath, endpoint_url, validate_bot_endpoint
from poker_bot_platform.bots.parsing import DuplicateKeyError, parse_json_strict
from poker_bot_platform.domain.models import ActionType, FailureReason, PlayerAction

REQUEST_LIMIT_BYTES = 64 * 1024
RESPONSE_LIMIT_BYTES = 4 * 1024
CONNECT_TIMEOUT_SECONDS = 0.5
TOTAL_TIMEOUT_SECONDS = 3.0

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class GatewayOutcome:
    action: PlayerAction
    response: BotActionResponse | None = None
    failure_reason: FailureReason | None = None

    @property
    def used_fallback(self) -> bool:
        return self.failure_reason is not None


@dataclass(frozen=True, slots=True)
class VerificationOutcome:
    verified: bool
    failure_reason: FailureReason | None = None


class _GatewayFailure(Exception):
    def __init__(self, reason: FailureReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


def deterministic_fallback(request: BotActionRequest) -> PlayerAction:
    action_types = {legal.action for legal in request.legal_actions}
    action = ActionType.CHECK if ActionType.CHECK in action_types else ActionType.FOLD
    return PlayerAction(
        decision_id=request.decision_id,
        table_version=request.table_version,
        seat=request.player.seat,
        action=action,
    )


def response_is_legal(request: BotActionRequest, response: BotActionResponse) -> bool:
    legal_by_type: dict[ActionType, BotLegalAction] = {
        legal.action: legal for legal in request.legal_actions
    }
    legal = legal_by_type.get(response.action)
    if legal is None:
        return False
    if response.action is not ActionType.RAISE:
        return response.amount_to is None
    assert response.amount_to is not None
    assert legal.min_amount_to is not None and legal.max_amount_to is not None
    return legal.min_amount_to <= response.amount_to <= legal.max_amount_to


class BotGateway:
    """The only network path from the platform to participant-controlled bots."""

    def __init__(
        self,
        *,
        participant_subnet: IPv4Network | IPv6Network,
        blocked_ips: tuple[str, ...] = (),
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        timeout = httpx.Timeout(
            timeout=TOTAL_TIMEOUT_SECONDS,
            connect=CONNECT_TIMEOUT_SECONDS,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._participant_subnet = participant_subnet
        self._blocked_ips = blocked_ips
        self._now = now or (lambda: datetime.now(UTC))

    async def __aenter__(self) -> BotGateway:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self, endpoint: BotEndpoint) -> HealthResponse | None:
        try:
            return await self._request_json(
                endpoint=endpoint,
                path=BotPath.HEALTH,
                method="GET",
                bearer_token=None,
                body=None,
                response_model=HealthResponse,
                timeout_seconds=TOTAL_TIMEOUT_SECONDS,
            )
        except _GatewayFailure:
            return None

    async def verify(
        self,
        endpoint: BotEndpoint,
        bearer_token: str,
        challenge: str,
    ) -> VerificationOutcome:
        request = VerifyRequest(protocol="poker-bot.v1", challenge=challenge)
        try:
            response = await self._request_json(
                endpoint=endpoint,
                path=BotPath.VERIFY,
                method="POST",
                bearer_token=bearer_token,
                body=request,
                response_model=VerifyResponse,
                timeout_seconds=TOTAL_TIMEOUT_SECONDS,
            )
        except _GatewayFailure as exc:
            return VerificationOutcome(verified=False, failure_reason=exc.reason)
        if response.challenge != challenge:
            return VerificationOutcome(verified=False, failure_reason=FailureReason.STALE)
        return VerificationOutcome(verified=True)

    async def request_action(
        self,
        endpoint: BotEndpoint,
        bearer_token: str,
        request: BotActionRequest,
    ) -> GatewayOutcome:
        remaining = (request.deadline_at.astimezone(UTC) - self._now()).total_seconds()
        if remaining <= 0:
            return self._fallback(request, FailureReason.TIMEOUT)
        try:
            response = await self._request_json(
                endpoint=endpoint,
                path=BotPath.ACTION,
                method="POST",
                bearer_token=bearer_token,
                body=request,
                response_model=BotActionResponse,
                timeout_seconds=min(TOTAL_TIMEOUT_SECONDS, remaining),
            )
        except _GatewayFailure as exc:
            return self._fallback(request, exc.reason)

        if self._now() >= request.deadline_at.astimezone(UTC):
            return self._fallback(request, FailureReason.TIMEOUT)
        if (
            response.tournament_id != request.tournament_id
            or response.table_id != request.table_id
            or response.hand_id != request.hand_id
            or response.decision_id != request.decision_id
            or response.table_version != request.table_version
        ):
            return self._fallback(request, FailureReason.STALE)
        if not response_is_legal(request, response):
            return self._fallback(request, FailureReason.ILLEGAL_ACTION)

        return GatewayOutcome(
            action=PlayerAction(
                decision_id=response.decision_id,
                table_version=response.table_version,
                seat=request.player.seat,
                action=response.action,
                amount_to=response.amount_to,
            ),
            response=response,
        )

    async def _request_json(
        self,
        *,
        endpoint: BotEndpoint,
        path: BotPath,
        method: str,
        bearer_token: str | None,
        body: BaseModel | None,
        response_model: type[ResponseModelT],
        timeout_seconds: float,
    ) -> ResponseModelT:
        try:
            endpoint = validate_bot_endpoint(
                str(endpoint.ip),
                endpoint.port,
                participant_subnet=self._participant_subnet,
                blocked_ips=self._blocked_ips,
            )
        except ValueError as exc:
            raise _GatewayFailure(FailureReason.CONNECTION) from exc

        content = body.model_dump_json().encode("utf-8") if body is not None else b""
        if len(content) > REQUEST_LIMIT_BYTES:
            raise _GatewayFailure(FailureReason.OVERSIZED)

        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if bearer_token is not None:
            headers["Authorization"] = f"Bearer {bearer_token}"

        outbound = self._client.build_request(
            method,
            endpoint_url(endpoint, path),
            headers=headers,
            content=content,
        )
        try:
            async with asyncio.timeout(timeout_seconds):
                response = await self._client.send(outbound, stream=True)
                try:
                    if response.status_code < 200 or response.status_code >= 300:
                        raise _GatewayFailure(FailureReason.HTTP_STATUS)
                    media_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if media_type.strip().lower() != "application/json":
                        raise _GatewayFailure(FailureReason.CONTENT_TYPE)
                    payload = await self._read_limited(response)
                finally:
                    await response.aclose()
        except _GatewayFailure:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise _GatewayFailure(FailureReason.TIMEOUT) from exc
        except httpx.HTTPError as exc:
            raise _GatewayFailure(FailureReason.CONNECTION) from exc

        try:
            return parse_json_strict(payload, response_model)
        except DuplicateKeyError as exc:
            raise _GatewayFailure(FailureReason.MALFORMED_JSON) from exc
        except ValidationError as exc:
            raise _GatewayFailure(FailureReason.SCHEMA) from exc
        except ValueError as exc:
            raise _GatewayFailure(FailureReason.MALFORMED_JSON) from exc

    @staticmethod
    async def _read_limited(response: httpx.Response) -> bytes:
        declared_length = response.headers.get("content-length")
        if declared_length is not None:
            try:
                if int(declared_length) > RESPONSE_LIMIT_BYTES:
                    raise _GatewayFailure(FailureReason.OVERSIZED)
            except ValueError as exc:
                raise _GatewayFailure(FailureReason.HTTP_STATUS) from exc

        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > RESPONSE_LIMIT_BYTES:
                raise _GatewayFailure(FailureReason.OVERSIZED)
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _fallback(request: BotActionRequest, reason: FailureReason) -> GatewayOutcome:
        return GatewayOutcome(
            action=deterministic_fallback(request),
            failure_reason=reason,
        )
