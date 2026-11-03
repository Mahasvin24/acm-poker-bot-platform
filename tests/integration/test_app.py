from __future__ import annotations

from fastapi.testclient import TestClient

from poker_bot_platform.app import create_app
from poker_bot_platform.config import Settings
from poker_bot_platform.integration import GameplayScheduler

from .match_stack import build_stack


def test_application_factory_mounts_match_api_without_connecting_to_database() -> None:
    application = create_app(
        Settings(
            database_url="postgresql+asyncpg://unused:unused@localhost:5432/unused",
            secret_key="3f9c1a7e5b2d8046c9e1f7a3b5d20e84",
            participant_subnet="192.168.1.0/24",
        )
    )
    with TestClient(application) as client:
        assert application.state.gameplay_scheduler.running
        response = client.get("/health")
    assert not application.state.gameplay_scheduler.running
    assert response.status_code == 200
    paths = set(application.openapi()["paths"])
    for path in (
        "/api/v1/auth/login",
        "/api/v1/bots",
        "/api/v1/matches/join",
        "/api/v1/matches/code/{code}",
        "/api/v1/matches/{match_id}/table",
        "/api/v1/matches/{match_id}/table/action",
        "/api/v1/admin/matches",
        "/api/v1/admin/matches/{match_id}/start",
        "/api/v1/admin/matches/{match_id}/table",
    ):
        assert path in paths
    assert not any("tournament" in path for path in paths)


async def test_scheduler_discovers_and_drives_running_matches() -> None:
    stack = await build_stack()
    owner = await stack.user("owner@example.com")
    match_id, code = await stack.create_match()
    for index in range(2):
        profile = await stack.verified_bot(owner, f"Bot {index}", f"10.20.0.{30 + index}")
        await stack.join_bot(owner, code, profile)
    await stack.matches.start(stack.admin, match_id)

    scheduler = GameplayScheduler(stack.registry, stack.runtime)
    await scheduler.run_once(now=0.0)
    view = await stack.runtime.spectator_state(match_id)
    assert view.hand_number >= 1
    assert view.action_history or view.hand_number > 1
