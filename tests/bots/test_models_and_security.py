from __future__ import annotations

import json
from ipaddress import ip_network
from pathlib import Path

import pytest
from pydantic import ValidationError

from poker_bot_platform.bots.conformance import conformance_request
from poker_bot_platform.bots.factory import action_request_from_snapshot
from poker_bot_platform.bots.models import BotActionResponse
from poker_bot_platform.bots.network import BotPath, endpoint_url, validate_bot_endpoint
from poker_bot_platform.bots.parsing import DuplicateKeyError, parse_json_strict
from poker_bot_platform.bots.tokens import (
    EncryptedTokenStore,
    generate_bearer_token,
    generate_verification_challenge,
)
from poker_bot_platform.domain.models import (
    ActionType,
    EntryKind,
    HandSnapshot,
    LegalAction,
    PendingDecision,
    SeatState,
    Street,
)


def test_action_request_exposes_only_acting_players_cards() -> None:
    wire = conformance_request().model_dump(mode="json")
    assert wire["player"]["hole_cards"] == ["As", "Kd"]
    assert all("hole_cards" not in seat for seat in wire["table"]["seats"])
    assert "deck" not in json.dumps(wire).lower()


def test_wire_models_forbid_extras_and_coercion() -> None:
    valid = {
        "protocol": "poker-bot.v1",
        "tournament_id": "t",
        "table_id": "table",
        "hand_id": "hand",
        "decision_id": "decision",
        "table_version": 2,
        "action": "check",
    }
    with pytest.raises(ValidationError):
        BotActionResponse.model_validate({**valid, "unexpected": True})
    with pytest.raises(ValidationError):
        BotActionResponse.model_validate({**valid, "table_version": "2"})
    with pytest.raises(ValidationError):
        BotActionResponse.model_validate({**valid, "table_version": True})


def test_request_requires_a_legal_deterministic_fallback() -> None:
    request = conformance_request().model_dump()
    request["legal_actions"] = [{"action": "call", "amount": 200}]
    with pytest.raises(ValidationError, match="deterministic fallback"):
        type(conformance_request()).model_validate(request)


def test_snapshot_converter_strips_deck_and_other_private_cards() -> None:
    snapshot = HandSnapshot(
        adapter_version="test",
        tournament_id="tournament",
        table_id="table",
        hand_id="hand",
        hand_number=1,
        table_version=4,
        street=Street.PREFLOP,
        button_seat=1,
        small_blind=100,
        big_blind=200,
        big_blind_ante=200,
        deck_order=("2c", "3c", "4c", "5c"),
        seats=(
            SeatState(
                seat=1,
                entrant_id="bot",
                display_name="Bot",
                kind=EntryKind.BOT,
                stack=19_800,
                hole_cards=("As", "Kd"),
            ),
            SeatState(
                seat=2,
                entrant_id="human",
                display_name="Human",
                kind=EntryKind.HUMAN,
                stack=19_800,
                hole_cards=("Qh", "Qs"),
            ),
        ),
        acting_seat=1,
        legal_actions=(LegalAction(action=ActionType.CHECK),),
    )
    pending = PendingDecision(
        decision_id="decision",
        table_id="table",
        hand_id="hand",
        table_version=4,
        seat=1,
        deadline_at=conformance_request().deadline_at,
        legal_actions=snapshot.legal_actions,
    )
    wire = action_request_from_snapshot(snapshot, pending).model_dump(mode="json")
    serialized = json.dumps(wire)
    assert wire["player"]["hole_cards"] == ["As", "Kd"]
    assert "Qh" not in serialized and "Qs" not in serialized
    assert "deck_order" not in serialized

    inconsistent = pending.model_copy(
        update={"legal_actions": (LegalAction(action=ActionType.FOLD),)}
    )
    with pytest.raises(ValueError, match="legal actions"):
        action_request_from_snapshot(snapshot, inconsistent)


def test_strict_parser_rejects_duplicate_keys() -> None:
    payload = (
        b'{"protocol":"poker-bot.v1","tournament_id":"t","table_id":"x",'
        b'"hand_id":"h","decision_id":"d","table_version":1,'
        b'"action":"check","action":"fold"}'
    )
    with pytest.raises(DuplicateKeyError):
        parse_json_strict(payload, BotActionResponse)


@pytest.mark.parametrize(
    "ip",
    [
        "localhost",
        "127.0.0.1",
        "169.254.1.1",
        "224.0.0.1",
        "192.168.0.0",
        "192.168.255.255",
        "10.0.0.9",
        " 192.168.1.20",
    ],
)
def test_endpoint_validation_rejects_nonparticipant_or_infrastructure_addresses(ip: str) -> None:
    with pytest.raises((ValueError, ValidationError)):
        validate_bot_endpoint(
            ip,
            8001,
            participant_subnet=ip_network("192.168.0.0/16"),
        )


def test_endpoint_validation_blocks_host_and_constructs_fixed_paths() -> None:
    network = ip_network("192.168.0.0/16")
    with pytest.raises(ValueError, match="infrastructure"):
        validate_bot_endpoint(
            "192.168.1.1",
            8001,
            participant_subnet=network,
            blocked_ips=("192.168.1.1",),
        )
    endpoint = validate_bot_endpoint(
        "192.168.1.20",
        8001,
        participant_subnet=network,
    )
    assert endpoint_url(endpoint, BotPath.ACTION) == "http://192.168.1.20:8001/v1/action"


def test_token_storage_round_trip_and_tamper_rejection() -> None:
    store = EncryptedTokenStore.from_deployment_secret("s" * 32)
    token = generate_bearer_token()
    ciphertext = store.encrypt(token)
    assert token not in ciphertext
    assert store.matches(ciphertext, token)
    assert not store.matches(ciphertext, token + "x")
    assert not store.matches(ciphertext[:-2] + "xx", token)
    assert len(generate_verification_challenge()) >= 32


def test_published_schema_artifacts_are_valid_json_and_forbid_root_extras() -> None:
    schema_dir = Path(__file__).parents[2] / "schemas"
    schemas = sorted(schema_dir.glob("bot-*-v1.schema.json"))
    assert len(schemas) == 5
    for path in schemas:
        schema = json.loads(path.read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
