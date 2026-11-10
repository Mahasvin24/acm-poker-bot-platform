from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from poker_bot_platform.api.router import create_api_router

from ..integration.match_stack import MatchStack, build_stack

ORIGIN = "http://localhost:3000"
HEADERS = {"Origin": ORIGIN}


@pytest.fixture
async def stack() -> MatchStack:
    return await build_stack()


@pytest.fixture
async def app(stack: MatchStack) -> FastAPI:
    application = FastAPI()
    application.include_router(
        create_api_router(
            auth=stack.auth,
            bots=stack.bots,
            matches=stack.matches,
            runtime=stack.runtime,
            allowed_origin=ORIGIN,
        )
    )
    return application


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers=HEADERS,
    )


@pytest.fixture
async def admin(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(app) as client:
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin-long-password"},
        )
        assert response.status_code == 200
        yield client


@asynccontextmanager
async def signed_in(
    app: FastAPI, email: str, kind: str = "human"
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(app) as client:
        credentials = {"email": email, "password": "long-enough-password"}
        registered = await client.post(
            "/api/v1/auth/register", json={**credentials, "participant_kind": kind}
        )
        assert registered.status_code == 201
        assert (await client.post("/api/v1/auth/login", json=credentials)).status_code == 200
        yield client


async def test_mutations_require_same_origin_and_login_is_rate_limited(app: FastAPI) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as bare:
        response = await bare.post(
            "/api/v1/auth/register",
            json={"email": "a@example.com", "password": "long-enough-password"},
        )
        assert response.status_code == 403

    async with client_for(app) as client:
        duplicate = {
            "email": "admin@example.com",
            "password": "long-enough-password",
            "participant_kind": "human",
        }
        conflict = await client.post("/api/v1/auth/register", json=duplicate)
        assert conflict.status_code == 409
        assert "sign in" in conflict.json()["detail"]

        statuses = [
            (
                await client.post(
                    "/api/v1/auth/login",
                    json={"email": "admin@example.com", "password": "wrong-password"},
                )
            ).status_code
            for _ in range(6)
        ]
        assert statuses == [401] * 5 + [429]
        locked = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "admin-long-password"},
        )
        assert locked.status_code == 429
        assert int(locked.headers["retry-after"]) > 0


async def test_bot_profiles_reveal_tokens_only_to_the_owner_and_verify(app: FastAPI, stack: MatchStack) -> None:
    async with signed_in(app, "owner@example.com", "bot") as owner:
        created = await owner.post(
            "/api/v1/bots", json={"name": "Atlas", "ip": "10.20.0.11", "port": 8001}
        )
        assert created.status_code == 201
        assert created.headers["cache-control"] == "no-store"
        body = created.json()
        token = body["bearer_token"]
        bot_id = body["bot"]["id"]
        assert body["bot"]["verified_at"] is None

        second = await owner.post(
            "/api/v1/bots", json={"name": "Another bot", "ip": "10.20.0.12", "port": 8001}
        )
        assert second.status_code == 409
        assert "already have a bot" in second.json()["detail"]

        listed = await owner.get("/api/v1/bots")
        assert token not in listed.text

        unreachable = await owner.post(f"/api/v1/bots/{bot_id}/verify")
        assert unreachable.status_code == 409
        assert "bearer token" in unreachable.json()["detail"]

        stack.network.tokens["10.20.0.11"] = token
        verified = await owner.post(f"/api/v1/bots/{bot_id}/verify")
        assert verified.status_code == 200
        assert verified.json()["verified_at"] is not None
        assert verified.json()["last_verification_error"] is None

        revealed = await owner.post(f"/api/v1/bots/{bot_id}/token")
        assert revealed.status_code == 200
        assert revealed.headers["cache-control"] == "no-store"
        assert revealed.json()["bearer_token"] == token
        assert revealed.json()["bot"]["verified_at"] == verified.json()["verified_at"]
        assert token not in (await owner.get("/api/v1/bots")).text

        assert stack.network.calls[("10.20.0.11", "/v1/health")] == 2
        verify_calls = stack.network.calls[("10.20.0.11", "/v1/verify")]
        stack.network.broken.add("10.20.0.11")
        failed_health = await owner.post(f"/api/v1/bots/{bot_id}/verify")
        assert failed_health.status_code == 409
        assert "Health check failed at /v1/health" in failed_health.json()["detail"]
        assert stack.network.calls[("10.20.0.11", "/v1/verify")] == verify_calls
        failed_profile = (await owner.get("/api/v1/bots")).json()[0]
        assert failed_profile["verified_at"] is None
        assert "Health check failed" in failed_profile["last_verification_error"]
        stack.network.broken.clear()
        assert (await owner.post(f"/api/v1/bots/{bot_id}/verify")).status_code == 200

        bad_ip = await owner.post(
            "/api/v1/bots", json={"name": "Local", "ip": "127.0.0.1", "port": 8001}
        )
        assert bad_ip.status_code == 409
        assert "event network" in bad_ip.json()["detail"]

        diagnostics = await owner.get(f"/api/v1/bots/{bot_id}/diagnostics")
        assert diagnostics.status_code == 200
        assert diagnostics.json()["decisions"] == 0

    async with signed_in(app, "other@example.com") as other:
        assert (await other.post(f"/api/v1/bots/{bot_id}/verify")).status_code == 404
        assert (await other.post(f"/api/v1/bots/{bot_id}/token")).status_code == 404

    async with client_for(app) as guest:
        assert (await guest.post(f"/api/v1/bots/{bot_id}/token")).status_code == 401


async def test_admin_creates_match_and_players_join_by_code(
    app: FastAPI, stack: MatchStack, admin: httpx.AsyncClient
) -> None:
    async with signed_in(app, "player@example.com") as player:
        forbidden = await player.post("/api/v1/admin/matches", json={"name": "Nope"})
        assert forbidden.status_code == 403

    created = await admin.post(
        "/api/v1/admin/matches",
        json={"name": "Friday", "config": {"max_seats": 3, "starting_stack": 5_000}},
    )
    assert created.status_code == 201
    match = created.json()
    code = match["join_code"]
    assert len(code) == 7 and code[3] == "-"

    async with signed_in(app, "ava@example.com") as ava:
        preview = await ava.get(f"/api/v1/matches/code/{code.lower()}")
        assert preview.status_code == 200
        assert preview.json()["joinable"]
        assert preview.json()["name"] == "Friday"

        missing = await ava.get("/api/v1/matches/code/ZZZ-ZZZ")
        assert missing.status_code == 404

        joined = await ava.post(
            "/api/v1/matches/join",
            json={"code": code, "kind": "human", "display_name": "Ava"},
        )
        assert joined.status_code == 201
        assert [entry["display_name"] for entry in joined.json()["entries"]] == ["Ava"]

        not_started = await ava.get(f"/api/v1/matches/{match['match_id']}/table")
        assert not_started.status_code == 409
        assert "not started" in not_started.json()["detail"]

        mine = await ava.get("/api/v1/me/matches")
        assert [item["match_id"] for item in mine.json()] == [match["match_id"]]

    async with signed_in(app, "owner@example.com", "bot") as owner:
        created_bot = (
            await owner.post(
                "/api/v1/bots", json={"name": "Atlas", "ip": "10.20.0.11", "port": 8001}
            )
        ).json()
        unverified = await owner.post(
            "/api/v1/matches/join",
            json={"code": code, "kind": "bot", "bot_profile_id": created_bot["bot"]["id"]},
        )
        assert unverified.status_code == 409
        assert "verify" in unverified.json()["detail"]

        stack.network.tokens["10.20.0.11"] = created_bot["bearer_token"]
        await owner.post(f"/api/v1/bots/{created_bot['bot']['id']}/verify")
        bot_joined = await owner.post(
            "/api/v1/matches/join",
            json={"code": code, "kind": "bot", "bot_profile_id": created_bot["bot"]["id"]},
        )
        assert bot_joined.status_code == 201
        assert any(
            entry["display_name"] == "Atlas" and entry["bot_ready"]
            for entry in bot_joined.json()["entries"]
        )

    detail = await admin.get(f"/api/v1/admin/matches/{match['match_id']}")
    entries = detail.json()["entries"]
    assert {entry["account_email"] for entry in entries} == {
        "ava@example.com",
        "owner@example.com",
    }
    assert next(entry for entry in entries if entry["kind"] == "bot")["bot_ready"]

    listed = await admin.get("/api/v1/admin/matches")
    assert listed.json()[0]["seats_taken"] == 2

    started = await admin.post(f"/api/v1/admin/matches/{match['match_id']}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    await stack.drive(match["match_id"])
    spectate = await admin.get(f"/api/v1/admin/matches/{match['match_id']}/table")
    assert spectate.status_code == 200
    assert spectate.json()["viewer_seat"] is None
    assert all(seat["hole_cards"] == [] for seat in spectate.json()["seats"])

    async with signed_in(app, "late@example.com") as late:
        rejected = await late.post(
            "/api/v1/matches/join",
            json={"code": code, "kind": "human", "display_name": "Late"},
        )
        assert rejected.status_code == 409
        assert "already started" in rejected.json()["detail"]


async def test_kick_leave_codes_and_rate_limited_code_guessing(
    app: FastAPI, admin: httpx.AsyncClient
) -> None:
    match = (await admin.post("/api/v1/admin/matches", json={"name": "Lobby"})).json()
    match_id = match["match_id"]

    async with signed_in(app, "ben@example.com") as ben:
        joined = (
            await ben.post(
                "/api/v1/matches/join",
                json={"code": match["join_code"], "kind": "human", "display_name": "Ben"},
            )
        ).json()
        entry_id = joined["entries"][0]["entry_id"]
        kicked = await admin.delete(f"/api/v1/admin/matches/{match_id}/entries/{entry_id}")
        assert kicked.status_code == 200
        assert kicked.json()["entries"] == []

        rejoined = (
            await ben.post(
                "/api/v1/matches/join",
                json={"code": match["join_code"], "kind": "human", "display_name": "Ben"},
            )
        ).json()
        left = await ben.delete(
            f"/api/v1/matches/{match_id}/entries/{rejoined['entries'][0]['entry_id']}"
        )
        assert left.status_code == 204
        assert (await ben.get(f"/api/v1/matches/{match_id}")).status_code == 404

        regenerated = await admin.post(f"/api/v1/admin/matches/{match_id}/code")
        new_code = regenerated.json()["join_code"]
        assert new_code != match["join_code"]
        assert (await ben.get(f"/api/v1/matches/code/{match['join_code']}")).status_code == 404
        assert (await ben.get(f"/api/v1/matches/code/{new_code}")).status_code == 200

        revoked = await admin.delete(f"/api/v1/admin/matches/{match_id}/code")
        assert revoked.json()["join_code"] is None

    async with signed_in(app, "guesser@example.com") as guesser:
        statuses = [
            (await guesser.get("/api/v1/matches/code/ZZZ-ZZ2")).status_code for _ in range(21)
        ]
        assert statuses[:20] == [404] * 20
        assert statuses[20] == 429


async def test_admin_can_reset_a_forgotten_password(app: FastAPI, admin: httpx.AsyncClient) -> None:
    async with signed_in(app, "forgetful@example.com") as user:
        me = (await user.get("/api/v1/auth/me")).json()
        accounts = await admin.get("/api/v1/admin/accounts")
        assert me["email"] in {item["email"] for item in accounts.json()}

        reset = await admin.post(f"/api/v1/admin/accounts/{me['id']}/reset-password")
        assert reset.status_code == 200
        temporary = reset.json()["temporary_password"]
        assert (await user.get("/api/v1/auth/me")).status_code == 401

        login = await user.post(
            "/api/v1/auth/login", json={"email": me["email"], "password": temporary}
        )
        assert login.status_code == 200
        changed = await user.post(
            "/api/v1/auth/password",
            json={"current_password": temporary, "new_password": "a-fresh-long-password"},
        )
        assert changed.status_code == 200


@pytest.mark.parametrize("kind", ["human", "bot"])
async def test_signup_kind_is_required_and_survives_login(app: FastAPI, kind: str) -> None:
    async with client_for(app) as client:
        credentials = {"email": f"{kind}@example.com", "password": "long-enough-password"}
        missing = await client.post("/api/v1/auth/register", json=credentials)
        assert missing.status_code == 422
        invalid = await client.post(
            "/api/v1/auth/register", json={**credentials, "participant_kind": "admin"}
        )
        assert invalid.status_code == 422
        created = await client.post(
            "/api/v1/auth/register", json={**credentials, "participant_kind": kind}
        )
        assert created.status_code == 201
        assert created.json()["participant_kind"] == kind
        logged_in = await client.post("/api/v1/auth/login", json=credentials)
        assert logged_in.json()["participant_kind"] == kind
        assert (await client.get("/api/v1/auth/me")).json()["participant_kind"] == kind


async def test_account_kind_controls_bot_creation_and_match_entry(
    app: FastAPI, stack: MatchStack
) -> None:
    _, code = await stack.create_match()
    async with signed_in(app, "human-kind@example.com") as human:
        created = await human.post(
            "/api/v1/bots", json={"name": "Nope", "ip": "10.20.0.11", "port": 8001}
        )
        assert created.status_code == 403
        wrong_kind = await human.post(
            "/api/v1/matches/join", json={"code": code, "kind": "bot", "bot_profile_id": "fake"}
        )
        assert wrong_kind.status_code == 409
        assert "as human" in wrong_kind.json()["detail"]
    async with signed_in(app, "bot-kind@example.com", "bot") as bot:
        wrong_kind = await bot.post(
            "/api/v1/matches/join", json={"code": code, "kind": "human", "display_name": "Nope"}
        )
        assert wrong_kind.status_code == 409
        assert "as bot" in wrong_kind.json()["detail"]


async def test_bot_settings_survive_edit_and_new_session_without_changing_token(
    app: FastAPI, stack: MatchStack
) -> None:
    async with signed_in(app, "persistent@example.com", "bot") as client:
        created = (await client.post(
            "/api/v1/bots", json={"name": "Atlas", "ip": "10.20.0.11", "port": 8001}
        )).json()
        bot_id = created["bot"]["id"]
        token = created["bearer_token"]
        stack.network.tokens["10.20.0.11"] = token
        assert (await client.post(f"/api/v1/bots/{bot_id}/verify")).status_code == 200
        renamed = await client.patch(f"/api/v1/bots/{bot_id}", json={"name": "River"})
        assert renamed.json()["verified_at"] is not None
        updated = await client.patch(
            f"/api/v1/bots/{bot_id}", json={"name": "River", "ip": "10.20.0.12", "port": 9000}
        )
        assert updated.status_code == 200
        assert updated.json()["verified_at"] is None
        assert token not in updated.text
        cannot_edit_token = await client.patch(
            f"/api/v1/bots/{bot_id}", json={"bearer_token": "replacement"}
        )
        assert cannot_edit_token.status_code == 422
        await client.post("/api/v1/auth/logout")
    async with client_for(app) as client:
        await client.post("/api/v1/auth/login", json={
            "email": "persistent@example.com", "password": "long-enough-password"
        })
        saved = (await client.get("/api/v1/bots")).json()[0]
        assert (saved["name"], saved["ip"], saved["port"]) == ("River", "10.20.0.12", 9000)
        assert token not in str(saved)
        stack.network.tokens["10.20.0.12"] = token
        assert (await client.post(f"/api/v1/bots/{bot_id}/verify")).status_code == 200


async def test_players_signal_match_interest_and_admin_sees_latest_first(
    app: FastAPI, stack: MatchStack, admin: httpx.AsyncClient
) -> None:
    async with signed_in(app, "human-interest@example.com", "human") as human, signed_in(
        app, "bot-interest@example.com", "bot"
    ) as bot:
        before = (await human.get("/api/v1/auth/me")).json()
        assert before["looking_for_match_at"] is None
        first = (await human.post("/api/v1/auth/looking-for-match")).json()
        assert first["looking_for_match_at"] == stack.clock().isoformat().replace("+00:00", "Z")
        stack.clock.advance(10)
        second = (await bot.post("/api/v1/auth/looking-for-match")).json()
        accounts = (await admin.get("/api/v1/admin/accounts")).json()
        assert [row["id"] for row in accounts[:2]] == [second["id"], first["id"]]
        stack.clock.advance(5)
        refreshed = (await human.post("/api/v1/auth/looking-for-match")).json()
        assert refreshed["looking_for_match_at"] != first["looking_for_match_at"]
        persisted = (await human.get("/api/v1/auth/me")).json()
        assert persisted["looking_for_match_at"] == refreshed["looking_for_match_at"]
        accounts = (await admin.get("/api/v1/admin/accounts")).json()
        assert accounts[0]["id"] == first["id"]
        assert (await human.get("/api/v1/admin/accounts")).status_code == 403
    async with client_for(app) as guest:
        assert (await guest.post("/api/v1/auth/looking-for-match")).status_code == 401
