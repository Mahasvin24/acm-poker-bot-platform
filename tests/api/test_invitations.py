from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from poker_bot_platform.match import MatchCoordinator

from ..integration.match_stack import MatchStack
from .test_router import (
    admin as admin_fixture,
)
from .test_router import (
    app as app_fixture,
)
from .test_router import (
    client_for,
    signed_in,
)
from .test_router import (
    stack as stack_fixture,
)

admin = admin_fixture
app = app_fixture
stack = stack_fixture


async def test_admin_invites_and_player_accepts_without_join_code(
    app: FastAPI,
    admin: httpx.AsyncClient,
    stack: MatchStack,
) -> None:
    async with (
        signed_in(app, "invitee@example.com") as player,
        signed_in(app, "outsider@example.com") as other,
    ):
        account = (await player.get("/api/v1/auth/me")).json()
        match = (
            await admin.post("/api/v1/admin/matches", json={"name": "Invitation night"})
        ).json()
        match_id = match["match_id"]
        path = f"/api/v1/admin/matches/{match_id}/invitations"
        invited = await admin.post(path, json={"account_id": account["id"]})
        assert invited.status_code == 200
        assert invited.json()["entries"] == []
        assert invited.json()["invitations"][0]["status"] == "pending"
        duplicate = await admin.post(path, json={"account_id": account["id"]})
        assert len(duplicate.json()["invitations"]) == 1
        assert (await player.post(path, json={"account_id": account["id"]})).status_code == 403
        await admin.delete(f"/api/v1/admin/matches/{match_id}/code")
        assert (await player.get("/api/v1/me/invitations")).json()[0]["match_id"] == match_id
        assert (await other.get("/api/v1/me/invitations")).json() == []
        accept = f"/api/v1/matches/{match_id}/invitation/accept"
        assert (await other.post(accept, json={})).status_code == 404
        results = await asyncio.gather(
            *(player.post(accept, json={"display_name": "Ava"}) for _ in range(2))
        )
        assert all(item.status_code == 200 for item in results)
        assert len(results[-1].json()["entries"]) == 1
        assert results[-1].json()["entries"][0]["display_name"] == "Ava"
        assert (await player.get("/api/v1/me/invitations")).json() == []
        state = (await stack.registry.get(match_id)).state
        restored = await MatchCoordinator.restore(match_id, stack.registry._store)
        assert restored.state.invitations == state.invitations
        assert restored.state.invitations[0].status == "accepted"


async def test_invites_can_be_declined_resent_and_reject_started_or_full_matches(
    app: FastAPI,
    admin: httpx.AsyncClient,
) -> None:
    async with (
        signed_in(app, "one@example.com") as one,
        signed_in(app, "two@example.com") as two,
        signed_in(app, "three@example.com") as three,
    ):
        accounts = [(await client.get("/api/v1/auth/me")).json() for client in (one, two, three)]
        match = (
            await admin.post(
                "/api/v1/admin/matches", json={"name": "Two seats", "config": {"max_seats": 2}}
            )
        ).json()
        mid = match["match_id"]
        invite = f"/api/v1/admin/matches/{mid}/invitations"
        for account in accounts:
            assert (await admin.post(invite, json={"account_id": account["id"]})).status_code == 200
        decline = f"/api/v1/matches/{mid}/invitation/decline"
        assert (await three.post(decline)).status_code == 204
        assert (await three.get("/api/v1/me/invitations")).json() == []
        accept = f"/api/v1/matches/{mid}/invitation/accept"
        assert (await three.post(accept, json={})).status_code == 409
        assert (await admin.post(invite, json={"account_id": accounts[2]["id"]})).status_code == 200
        assert (await one.post(accept, json={})).status_code == 200
        assert (await two.post(accept, json={})).status_code == 200
        assert (await three.post(accept, json={})).status_code == 409
        assert (await admin.post(f"/api/v1/admin/matches/{mid}/start")).status_code == 200
        assert (await three.get("/api/v1/me/invitations")).json() == []
        assert (await three.post(accept, json={})).status_code == 409
        assert (await admin.post(invite, json={"account_id": accounts[2]["id"]})).status_code == 409


async def test_bot_invitation_uses_owned_verified_bot(
    app: FastAPI, admin: httpx.AsyncClient, stack: MatchStack
) -> None:
    async with signed_in(app, "builder@example.com", "bot") as builder:
        account = (await builder.get("/api/v1/auth/me")).json()
        match = (await admin.post("/api/v1/admin/matches", json={"name": "Bots welcome"})).json()
        mid = match["match_id"]
        await admin.post(
            f"/api/v1/admin/matches/{mid}/invitations", json={"account_id": account["id"]}
        )
        accept = f"/api/v1/matches/{mid}/invitation/accept"
        assert (await builder.post(accept, json={})).status_code == 409
        bot = (
            await builder.post(
                "/api/v1/bots", json={"name": "Reaper", "ip": "10.20.0.11", "port": 8001}
            )
        ).json()
        stack.network.tokens["10.20.0.11"] = bot["bearer_token"]
        assert (await builder.post(accept, json={})).status_code == 409
        await builder.post(f"/api/v1/bots/{bot['bot']['id']}/verify")
        accepted = await builder.post(accept, json={})
        assert accepted.status_code == 200
        assert accepted.json()["entries"][0]["kind"] == "bot"
        assert accepted.json()["entries"][0]["display_name"] == "Reaper"


async def test_looking_for_match_can_be_cancelled(app: FastAPI, admin: httpx.AsyncClient) -> None:
    async with signed_in(app, "cancel@example.com") as player:
        assert (await player.post("/api/v1/auth/looking-for-match")).json()["looking_for_match_at"]
        cancelled = await player.delete("/api/v1/auth/looking-for-match")
        assert cancelled.status_code == 200
        assert cancelled.json()["looking_for_match_at"] is None
        assert (await player.get("/api/v1/auth/me")).json()["looking_for_match_at"] is None
        listed = (await admin.get("/api/v1/admin/accounts")).json()
        assert (
            next(row for row in listed if row["email"] == "cancel@example.com")[
                "looking_for_match_at"
            ]
            is None
        )
    async with client_for(app) as guest:
        assert (await guest.delete("/api/v1/auth/looking-for-match")).status_code == 401
