from __future__ import annotations

from ipaddress import ip_network

import httpx
import pytest
from fastapi import FastAPI

from poker_bot_platform.api.models import (
    AdminCommandResponse,
    AdminTournamentStateResponse,
    PlayerActionRequest,
    PlayerTableStateResponse,
)
from poker_bot_platform.api.router import GameplayControlService, create_api_router
from poker_bot_platform.auth import (
    AuthService,
    EntrantService,
    InMemoryAuthRepository,
    bootstrap_admin,
)
from poker_bot_platform.bots import VerificationOutcome
from poker_bot_platform.bots.tokens import EncryptedTokenStore
from poker_bot_platform.domain import (
    ActionType,
    Street,
    TableStatus,
    TournamentConfig,
    TournamentStatus,
)

ORIGIN = "http://testserver"
HEADERS = {"Origin": ORIGIN}


class SuccessfulVerifier:
    async def verify(
        self, endpoint: object, bearer_token: str, challenge: str
    ) -> VerificationOutcome:
        return VerificationOutcome(verified=True)


class FakeAdmin:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def create_tournament(
        self,
        tournament_id: str,
        config: TournamentConfig,
        actor_id: str,
    ) -> AdminCommandResponse:
        self.calls.append(("create", tournament_id, actor_id))
        return AdminCommandResponse(tournament_id=tournament_id, status="draft")

    async def get_state(self, tournament_id: str) -> AdminTournamentStateResponse:
        self.calls.append(("get", tournament_id, "admin"))
        return AdminTournamentStateResponse(
            tournament_id=tournament_id,
            status=TournamentStatus.DRAFT,
            entrant_count=0,
            human_count=0,
            bot_count=0,
            verified_bot_count=0,
            table_count=0,
            level_number=1,
            phase_remaining_seconds=900,
            revision=0,
            config=TournamentConfig(),
        )

    async def update_draft(
        self,
        tournament_id: str,
        config: TournamentConfig,
        actor_id: str,
    ) -> AdminCommandResponse:
        self.calls.append(("update", tournament_id, actor_id))
        return AdminCommandResponse(tournament_id=tournament_id, status="draft")

    async def open_registration(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return self._record("open", tournament_id, actor_id, "registration_open")

    async def seat(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return self._record("seat", tournament_id, actor_id, "seated")

    async def start(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return self._record("start", tournament_id, actor_id, "running")

    async def pause(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return self._record("pause", tournament_id, actor_id, "pause_requested")

    async def resume(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return self._record("resume", tournament_id, actor_id, "running")

    async def advance_level(self, tournament_id: str, actor_id: str) -> AdminCommandResponse:
        return self._record("advance", tournament_id, actor_id, "running")

    def _record(
        self,
        command: str,
        tournament_id: str,
        actor_id: str,
        result_status: str,
    ) -> AdminCommandResponse:
        self.calls.append((command, tournament_id, actor_id))
        return AdminCommandResponse(tournament_id=tournament_id, status=result_status)


def make_services(
    gameplay: GameplayControlService | None = None,
) -> tuple[FastAPI, InMemoryAuthRepository, AuthService, FakeAdmin]:
    repository = InMemoryAuthRepository()
    auth = AuthService(repository)
    entrants = EntrantService(
        repository,
        token_store=EncryptedTokenStore.from_deployment_secret("s" * 32),
        participant_subnet=ip_network("192.168.0.0/16"),
        verifier=SuccessfulVerifier(),
    )
    admin = FakeAdmin()
    app = FastAPI()
    app.include_router(
        create_api_router(
            auth=auth,
            entrants=entrants,
            admin=admin,
            gameplay=gameplay,
            allowed_origin=ORIGIN,
        )
    )
    return app, repository, auth, admin


class FakeGameplay:
    def __init__(self) -> None:
        self.actions: list[PlayerActionRequest] = []

    async def player_state(
        self,
        account_id: str,
        tournament_id: str,
    ) -> PlayerTableStateResponse:
        return self._state(tournament_id)

    async def submit_human_action(
        self,
        account_id: str,
        tournament_id: str,
        request: PlayerActionRequest,
    ) -> PlayerTableStateResponse:
        self.actions.append(request)
        return self._state(tournament_id)

    @staticmethod
    def _state(tournament_id: str) -> PlayerTableStateResponse:
        return PlayerTableStateResponse(
            tournament_id=tournament_id,
            tournament_status=TournamentStatus.RUNNING,
            table_status=TableStatus.RUNNING,
            table_id="table-1",
            hand_id="hand-1",
            hand_number=1,
            table_version=0,
            viewer_seat=1,
            acting_seat=1,
            street=Street.PREFLOP,
            button_seat=1,
            small_blind=100,
            big_blind=200,
            big_blind_ante=200,
            community_cards=(),
            seats=(),
            pot=0,
            side_pots=(),
            action_history=(),
            completed=False,
        )


@pytest.mark.asyncio
async def test_register_login_me_logout_cookie_and_strict_body() -> None:
    app, repository, _, _ = make_services()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
    ) as client:
        rejected = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "person@example.com",
                "password": "long-enough-password",
                "role": "admin",
            },
            headers=HEADERS,
        )
        assert rejected.status_code == 422

        registered = await client.post(
            "/api/v1/auth/register",
            json={"email": "person@example.com", "password": "long-enough-password"},
            headers=HEADERS,
        )
        assert registered.status_code == 201
        assert registered.json()["role"] == "user"
        assert "password" not in registered.text

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "person@example.com", "password": "long-enough-password"},
            headers=HEADERS,
        )
        assert login.status_code == 200
        cookie = login.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert login.headers["cache-control"] == "no-store"
        raw_token = client.cookies["poker_session"]
        assert raw_token not in repository.sessions

        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "person@example.com"

        logout = await client.post("/api/v1/auth/logout", headers=HEADERS)
        assert logout.status_code == 204
        assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_mutations_require_exact_same_origin() -> None:
    app, _, _, _ = make_services()
    payload = {"email": "person@example.com", "password": "long-enough-password"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
    ) as client:
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 403
        response = await client.post(
            "/api/v1/auth/register",
            json=payload,
            headers={"Origin": "https://attacker.example"},
        )
        assert response.status_code == 403
        query_origin = await client.post(
            "/api/v1/auth/register",
            json=payload,
            headers={"Origin": f"{ORIGIN}?spoofed=true"},
        )
        assert query_origin.status_code == 403


@pytest.mark.asyncio
async def test_one_entrant_per_user_and_bot_endpoint_flow() -> None:
    app, _, _, _ = make_services()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
    ) as client:
        await client.post(
            "/api/v1/auth/register",
            json={"email": "bot@example.com", "password": "long-enough-password"},
            headers=HEADERS,
        )
        await client.post(
            "/api/v1/auth/login",
            json={"email": "bot@example.com", "password": "long-enough-password"},
            headers=HEADERS,
        )
        entrant = await client.post(
            "/api/v1/tournaments/t-1/entrant",
            json={"kind": "bot", "display_name": "Test Bot"},
            headers=HEADERS,
        )
        assert entrant.status_code == 201
        current = await client.get("/api/v1/tournaments/t-1/entrant")
        assert current.status_code == 200
        assert current.json()["display_name"] == "Test Bot"
        duplicate = await client.post(
            "/api/v1/tournaments/t-1/entrant",
            json={"kind": "human", "display_name": "Also Human"},
            headers=HEADERS,
        )
        assert duplicate.status_code == 409

        wrong_type = await client.put(
            "/api/v1/tournaments/t-1/entrant/bot-endpoint",
            json={"ip": "192.168.1.25", "port": "8001"},
            headers=HEADERS,
        )
        assert wrong_type.status_code == 422
        configured = await client.put(
            "/api/v1/tournaments/t-1/entrant/bot-endpoint",
            json={"ip": "192.168.1.25", "port": 8001},
            headers=HEADERS,
        )
        assert configured.status_code == 200
        assert configured.headers["cache-control"] == "no-store"
        assert configured.json()["bearer_token"]
        assert "ciphertext" not in configured.text

        verified = await client.post(
            "/api/v1/tournaments/t-1/entrant/bot-endpoint/verify",
            headers=HEADERS,
        )
        assert verified.status_code == 200
        assert verified.json()["bot_verified_at"] is not None


@pytest.mark.asyncio
async def test_admin_routes_require_explicit_admin_role() -> None:
    app, repository, auth, admin = make_services()
    await auth.register("user@example.com", "long-enough-password")
    await bootstrap_admin(repository, "owner@example.com", "long-enough-password")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
    ) as client:
        await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "long-enough-password"},
            headers=HEADERS,
        )
        forbidden = await client.post(
            "/api/v1/admin/tournaments",
            json={"tournament_id": "club-event"},
            headers=HEADERS,
        )
        assert forbidden.status_code == 403

        await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "long-enough-password"},
            headers=HEADERS,
        )
        created = await client.post(
            "/api/v1/admin/tournaments",
            json={"tournament_id": "club-event"},
            headers=HEADERS,
        )
        assert created.status_code == 201
        assert created.json() == {"tournament_id": "club-event", "status": "draft"}
        state = await client.get("/api/v1/admin/tournaments/club-event")
        assert state.status_code == 200
        assert state.json()["config"]["starting_stack"] == 20_000
        started = await client.post(
            "/api/v1/admin/tournaments/club-event/start",
            headers=HEADERS,
        )
        assert started.status_code == 200
        assert started.json()["status"] == "running"
        assert [call[0] for call in admin.calls] == ["create", "get", "start"]


@pytest.mark.asyncio
async def test_gameplay_read_requires_auth_and_action_requires_same_origin() -> None:
    gameplay = FakeGameplay()
    app, _, auth, _ = make_services(gameplay)
    await auth.register("player@example.com", "long-enough-password")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
    ) as client:
        unauthenticated = await client.get("/api/v1/tournaments/event/table")
        assert unauthenticated.status_code == 401
        await client.post(
            "/api/v1/auth/login",
            json={"email": "player@example.com", "password": "long-enough-password"},
            headers=HEADERS,
        )
        state = await client.get("/api/v1/tournaments/event/table")
        assert state.status_code == 200

        body = {
            "decision_id": "decision-1",
            "table_version": 0,
            "action": ActionType.CHECK.value,
        }
        rejected = await client.post(
            "/api/v1/tournaments/event/table/action",
            json=body,
        )
        assert rejected.status_code == 403
        accepted = await client.post(
            "/api/v1/tournaments/event/table/action",
            json=body,
            headers=HEADERS,
        )
        assert accepted.status_code == 200
        assert gameplay.actions[0].decision_id == "decision-1"
