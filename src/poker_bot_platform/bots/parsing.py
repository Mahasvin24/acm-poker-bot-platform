from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError


class DuplicateKeyError(ValueError):
    """Raised when externally supplied JSON repeats an object key."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json_strict[ModelT: BaseModel](payload: bytes, model: type[ModelT]) -> ModelT:
    """Decode one JSON object, rejecting duplicate keys and invalid wire types."""

    try:
        decoded = json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("top-level JSON value must be an object")
    try:
        return model.model_validate(decoded)
    except ValidationError:
        raise
