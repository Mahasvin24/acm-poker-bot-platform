"""End-to-end smoke test against a running platform.

Starts two reference bots in this process on the machine's LAN address, then drives the
public API exactly as the web app does: an admin creates a match, a builder registers and
verifies both bots and seats them by join code, a human joins and plays until the match
completes. Run it during rehearsal on the event network:

    python scripts/smoke_match.py --base-url http://localhost:3000 \
        --admin-email organizer@example.com --admin-password '...' --bot-ip 192.168.1.20
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx

from poker_bot_platform.bots.models import BOT_PROTOCOL_VERSION, BotActionRequest
from poker_bot_platform.bots.reference import deterministic_reference_action


def start_reference_bot(host: str) -> tuple[ThreadingHTTPServer, dict[str, str]]:
    state = {"token": ""}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def _send(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path == "/v1/health":
                self._send(200, {"protocol": BOT_PROTOCOL_VERSION, "status": "ready"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.headers.get("Authorization") != f"Bearer {state['token']}":
                self._send(401, {"error": "bad token"})
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/v1/verify":
                challenge = json.loads(body)["challenge"]
                self._send(200, {"protocol": BOT_PROTOCOL_VERSION, "challenge": challenge})
            elif self.path == "/v1/action":
                action = deterministic_reference_action(BotActionRequest.model_validate_json(body))
                self._send(200, action.model_dump(mode="json", exclude_none=True))
            else:
                self._send(404, {"error": "not found"})

    server = ThreadingHTTPServer((host, 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, headers={"Origin": base_url}, timeout=10)


def sign_up(base_url: str, email: str, password: str) -> httpx.Client:
    session = client(base_url)
    session.post("/api/v1/auth/register", json={"email": email, "password": password})
    session.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    ).raise_for_status()
    return session


def step(message: str) -> None:
    print(f"• {message}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("--bot-ip", required=True, help="this machine's LAN address")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    run = secrets.token_hex(3)

    admin = client(args.base_url)
    admin.post(
        "/api/v1/auth/login", json={"email": args.admin_email, "password": args.admin_password}
    ).raise_for_status()
    match = admin.post(
        "/api/v1/admin/matches",
        json={"name": f"Smoke {run}", "config": {"max_seats": 3, "starting_stack": 1_000}},
    ).json()
    code, match_id = match["join_code"], match["match_id"]
    step(f"created match {match_id} with code {code}")

    builder = sign_up(args.base_url, f"smoke-builder-{run}@example.com", "smoke-password-123")
    bots = []
    for index in range(2):
        server, state = start_reference_bot(args.bot_ip)
        created = builder.post(
            "/api/v1/bots",
            json={"name": f"Smoke Bot {index + 1}", "ip": args.bot_ip, "port": server.server_port},
        )
        created.raise_for_status()
        state["token"] = created.json()["bearer_token"]
        bot_id = created.json()["bot"]["id"]
        verified = builder.post(f"/api/v1/bots/{bot_id}/verify")
        if verified.status_code != 200:
            print(f"✗ verification failed: {verified.json()['detail']}")
            return 1
        joined = builder.post(
            "/api/v1/matches/join", json={"code": code, "kind": "bot", "bot_profile_id": bot_id}
        )
        joined.raise_for_status()
        bots.append(bot_id)
        step(f"bot {index + 1} on port {server.server_port} verified and seated")

    human = sign_up(args.base_url, f"smoke-human-{run}@example.com", "smoke-password-123")
    preview = human.get(f"/api/v1/matches/code/{code.lower()}").json()
    assert preview["joinable"], preview
    human.post(
        "/api/v1/matches/join", json={"code": code, "kind": "human", "display_name": "Smoke Human"}
    ).raise_for_status()
    step("human joined by code")

    started = admin.post(f"/api/v1/admin/matches/{match_id}/start")
    started.raise_for_status()
    step("match started")

    deadline = time.monotonic() + args.timeout
    actions = 0
    while time.monotonic() < deadline:
        table = human.get(f"/api/v1/matches/{match_id}/table")
        if table.status_code == 409:
            time.sleep(0.5)
            continue
        table.raise_for_status()
        state = table.json()
        if state["match_status"] == "completed":
            break
        decision = state.get("decision")
        if decision:
            legal = {item["action"]: item for item in decision["legal_actions"]}
            body: dict[str, Any] = {
                "decision_id": decision["decision_id"],
                "table_version": decision["table_version"],
            }
            if "raise" in legal and actions % 3 == 0:
                body |= {"action": "raise", "amount_to": legal["raise"]["max_amount_to"]}
            else:
                body["action"] = "check" if "check" in legal else "call"
            response = human.post(f"/api/v1/matches/{match_id}/table/action", json=body)
            if response.status_code not in (200, 409):
                response.raise_for_status()
            actions += 1
        time.sleep(0.3)
    else:
        print("✗ match did not finish before the timeout")
        return 1

    detail = admin.get(f"/api/v1/admin/matches/{match_id}").json()
    standings = [(item["position"], item["display_name"]) for item in detail["standings"]]
    step(f"match completed after {actions} human actions; standings {standings}")
    for bot_id in bots:
        diagnostics = builder.get(f"/api/v1/bots/{bot_id}/diagnostics").json()
        failures = sum(diagnostics["failures"].values())
        step(f"bot {bot_id[:8]}: {diagnostics['decisions']} decisions, {failures} fallbacks")
        if failures:
            print("✗ a healthy reference bot recorded fallbacks")
            return 1
    print("✓ smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
