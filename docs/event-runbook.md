# Event Deployment and Rehearsal Runbook

Use this procedure first in a full rehearsal, then again on event day. Record actual IPs, ports,
machine names, and drill results in a separate event worksheet; do not commit secrets here.

## 1. Freeze and prepare

- Check out the validated commit and keep an offline copy of the repository, Python environment,
  PostgreSQL image, and starter-bot files.
- Copy `.env.example` to `.env`. Generate the secret with `openssl rand -hex 32` (the server
  refuses placeholders), set the real participant subnet and browser origin, and block the
  router, server, and any infrastructure addresses in `POKER_BLOCKED_IPS`.
- Start PostgreSQL, wait for its health check, then run `alembic upgrade head`. Migration
  `0004_matches` recreates the gameplay tables; run it before any real data exists.
- Create the administrator with `poker-platform bootstrap-admin --email <address>`.
- Start the API with `uvicorn poker_bot_platform.app:app --host 0.0.0.0 --port 8000 --workers 1`
  and the frontend with `npm run build && npm run start` in `frontend/`.
- Verify `GET /health` and save a fresh database backup before players arrive.

## 2. Prove the network

- Disable AP/client isolation and connect the server by Ethernet when possible.
- Give the server a DHCP reservation. Verify every representative bot laptop can reach it.
- From the server, reach each bot's numeric address and port; confirm laptop firewalls allow it.
- Reconnect one bot laptop, check whether its address changes, and if so update it under
  **My Bots → Edit** and verify again.
- Run `python -m poker_bot_platform.bots.conformance` against Python and JavaScript bots on
  separate laptops.
- Run `python scripts/smoke_match.py --bot-ip <server LAN IP> …` on the server. It must end with
  `✓ smoke test passed`.

## 3. Dress rehearsal

- Create a match from `/admin`, project the join code, and have humans and bot builders join from
  their own devices. Start it from the console.
- Exercise folds, calls, bets, raises, all-ins, side pots, heads-up, pause/resume, end after hand,
  and cancel.
- During live decisions test: closing a human's browser (they should be marked **Away** after two
  timeouts), bot process death (the roster shows **Unresponsive** and the table keeps moving),
  slow and malformed bot responses (see **My Bots → Diagnostics**), API process restart, and a
  brief database stop.
- After each crash, confirm the table resumes without duplicate actions and an interrupted
  decision records one `restart_recovery` fallback.
- Confirm the spectator table shows no hole cards and no bot payload contains another player's
  unshown cards.
- Run a bot-only match on the event machine for at least eight hours. Accept only with zero chip
  drift, duplicate actions, stuck tables, unhandled exceptions, or unrecoverable snapshots.

## 4. Event-day checks

- Keep system time synchronized. Confirm disk space, power, database health, server IP, AP
  isolation, and participant subnet before admitting players.
- Keep a terminal ready for application and database logs and a tested restart. Do not edit
  poker state directly in PostgreSQL during play.
- Between matches, check the admin roster for **Unresponsive** bots and **Away** humans.
- Back up PostgreSQL after each match completes.

## 5. Recovery principles

- PostgreSQL unavailable: tables pause and retry automatically with backoff; restore the
  database and they resume from durable state. Never continue from memory alone.
- Bot unavailable or invalid: let the recorded check/fold fallback run; the breaker keeps the
  table fast. Do not pause a match for one bot.
- API process unavailable: restart the exact validated build with one worker. Do not clear
  pending decisions by hand.
- Router failure: pause after the current hand, restore the network, have builders update changed
  addresses and verify again, then resume.
- Engine invariant failure: the table stops and the console shows it; end the match to record
  standings and preserve logs and the database for review.
