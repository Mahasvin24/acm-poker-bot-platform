import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from poker_bot_platform.bots.conformance import conformance_request
from poker_bot_platform.bots.models import BotActionRequest, BotActionResponse
from poker_bot_platform.domain import ActionType

STARTER = Path(__file__).resolve().parents[2] / "examples" / "bots" / "python"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "actions,expected",
    [
        ([{"action": "check"}], ActionType.CHECK),
        ([{"action": "fold"}, {"action": "call", "amount": 300}], ActionType.CALL),
        ([{"action": "fold"}], ActionType.FOLD),
    ],
)
def test_python_strategy_is_editable_without_response_protocol(actions, expected) -> None:
    strategy = load("starter_strategy", STARTER / "strategy.py")
    payload = conformance_request().model_dump()
    payload["legal_actions"] = actions
    assert strategy.choose_action(BotActionRequest.model_validate(payload)) == (expected, None)


async def test_python_starter_keeps_authentication_and_response_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = load("starter_strategy", STARTER / "strategy.py")
    monkeypatch.setitem(sys.modules, "strategy", strategy)
    monkeypatch.setenv("BOT_TOKEN", "starter-test-token")
    app = load("starter_app", STARTER / "app.py").app
    request = conformance_request()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://bot"
    ) as client:
        assert (await client.get("/v1/health")).status_code == 200
        body = {"protocol": "poker-bot.v1", "challenge": "a" * 32}
        assert (await client.post("/v1/verify", json=body)).status_code == 401
        headers = {"Authorization": "Bearer starter-test-token"}
        assert (await client.post("/v1/verify", json=body, headers=headers)).json() == body
        assert (
            await client.post("/v1/action", json=request.model_dump(mode="json"))
        ).status_code == 401
        response = await client.post(
            "/v1/action", json=request.model_dump(mode="json"), headers=headers
        )
        parsed = BotActionResponse.model_validate(response.json())
        assert parsed.action is ActionType.CHECK
        for identifier in ["tournament_id", "table_id", "hand_id", "decision_id", "table_version"]:
            assert getattr(parsed, identifier) == getattr(request, identifier)
        assert "starter-test-token" not in response.text
