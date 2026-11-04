"""Generate the published JSON Schemas from the wire models.

Run ``python -m poker_bot_platform.bots.schemas`` after changing ``bots/models.py``;
the test suite fails when the files in ``schemas/`` are stale.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from poker_bot_platform.bots.models import (
    BOT_PROTOCOL_VERSION,
    BotActionRequest,
    BotActionResponse,
    HealthResponse,
    VerifyRequest,
    VerifyResponse,
)

_VERSION = BOT_PROTOCOL_VERSION.rsplit(".", 1)[-1]
_SCHEMAS: dict[str, tuple[type[BaseModel], str, str]] = {
    "action-request": (BotActionRequest, "Poker Bot Action Request", "serialization"),
    "action-response": (BotActionResponse, "Poker Bot Action Response", "validation"),
    "health-response": (HealthResponse, "Poker Bot Health Response", "validation"),
    "verify-request": (VerifyRequest, "Poker Bot Verify Request", "serialization"),
    "verify-response": (VerifyResponse, "Poker Bot Verify Response", "validation"),
}


def generate_schemas() -> dict[str, dict[str, Any]]:
    generated: dict[str, dict[str, Any]] = {}
    for name, (model, title, mode) in _SCHEMAS.items():
        filename = f"bot-{name}-{_VERSION}.schema.json"
        schema = model.model_json_schema(mode=mode)  # type: ignore[arg-type]
        schema.pop("title", None)
        generated[filename] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://acm.example/schemas/{filename}",
            "title": f"{title} {_VERSION}",
            **schema,
        }
    return generated


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> None:
    directory = Path(__file__).resolve().parents[3] / "schemas"
    for stale in directory.glob("bot-*.schema.json"):
        stale.unlink()
    for filename, schema in generate_schemas().items():
        (directory / filename).write_text(render(schema))
        print(f"wrote schemas/{filename}")


if __name__ == "__main__":
    main()
