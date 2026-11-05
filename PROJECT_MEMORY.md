# Project Memory

## Decisions

- **Matches replaced tournaments (v2)** — The product is code-joined single-table matches; multi-table tournaments, breaks, and balancing were removed on purpose, not deferred. Migration `0004_matches` drops and recreates gameplay tables because no real data existed, and it cannot be downgraded. Evidence: `src/poker_bot_platform/match/`, `migrations/versions/0004_matches.py`, `docs/architecture-plan.md`. Last verified: 2026-10-18.
- **Server-side pacing, humans only** — Presentation pauses (deal 3 s, action 1.5 s, street 2.5 s, hand end 5 s) live in `MatchRuntime` and apply only at tables with a seated human; the human decision clock opens after the pause. Client-side replay was rejected because it let the server clock run while the browser was still animating. Evidence: `PacingConfig` in `src/poker_bot_platform/integration/runtime.py`, `tests/integration/test_match_runtime.py::test_human_clock_starts_only_after_presentation_pauses`. Last verified: 2026-10-18.
- **Bots are account-owned profiles** — A bot is registered and verified once under My Bots and reused across matches; joining a match references the profile. Seats live only in match JSON state (`MatchState.entries`), not in a separate table. Evidence: `auth/models.py::BotProfile`, `match/models.py::MatchEntry`. Last verified: 2026-10-18.
- **Published bot schemas are generated** — `schemas/*.json` come from the Pydantic wire models via `python -m poker_bot_platform.bots.schemas`; a test fails if they are stale. Edit the models, never the JSON. Evidence: `src/poker_bot_platform/bots/schemas.py`, `tests/bots/test_models_and_security.py`. Last verified: 2026-10-18.

## Constraints and invariants

- **Event environment** — Participants share the event Wi-Fi; bots run on their owners' laptops at registered numeric LAN addresses inside `POKER_PARTICIPANT_SUBNET`. Real-router reachability is still unproven. Evidence: `docs/event-runbook.md`. Last verified: 2026-10-18.
- **Single process** — PostgreSQL is the durable authority and exactly one FastAPI worker is supported; rate limits, bot diagnostics, away state, and pacing are in-process memory and reset on restart. Evidence: `config.py::single_worker_only`, `api/rate_limit.py`. Last verified: 2026-10-18.
- **Scheduler is the only table driver** — `MatchRuntime.drive` runs only from `GameplayScheduler`, one background task per match; read endpoints must never drive tables or wait on bot I/O. Commands apply under the table coordinator lock and then call `wake()`. Evidence: `integration/scheduler.py`, `test_player_reads_do_not_wait_for_a_slow_bot`. Last verified: 2026-10-18.
- **Showdown privacy** — Hand results, table views, spectator views, and bot `previous_hand` use `public_hole_cards` (what PokerKit showed), never `hole_cards`, for anyone but the viewer. Evidence: `integration/presentation.py`, `bots/factory.py::previous_hand_from_snapshot`, `tests/integration/test_presentation.py`. Last verified: 2026-10-18.
- **Shared table presentation** — Player, spectator, demo, and preview tables all render through `PokerTableView`; containers own transport only. Evidence: `frontend/src/features/table/`. Last verified: 2026-10-18.

## Discoveries and gotchas

- **`TableCoordinator.restore()` marks "not found" as a database outage** — `TableNotFoundError` is a `PersistenceError`, so `restore()` sets `database_paused` before raising. Callers must build a fresh coordinator for a table that has not dealt its first hand. Evidence: `MatchRuntime._coordinator`. Last verified: 2026-10-18.
- **FastAPI routers with local dependency aliases** — `api/router.py` and `api/demo_router.py` must not use `from __future__ import annotations`; string annotations cannot resolve `Annotated[..., Depends(local_fn)]` aliases defined inside the factory. Evidence: those modules. Last verified: 2026-10-18.
- **`app` is built lazily** — `poker_bot_platform.app` creates `app` in a module `__getattr__` so importing `create_app` in tests does not require deployment settings. Evidence: `src/poker_bot_platform/app.py`. Last verified: 2026-10-18.
- **Alembic database configuration** — `migrations/env.py` reads `POKER_DATABASE_URL` only from the process environment, not `.env`; pass it inline for non-default databases. Postgres tests reset the schema rather than downgrading. Evidence: `migrations/env.py`, `tests/postgres.py`. Last verified: 2026-10-18.
- **One `next dev` per checkout** — Next.js 16 refuses a second dev server in the same `frontend/` directory, even on another port. Reuse the running one (the API must then allow its origin). Last verified: 2026-10-18.

## Open threads

- **Operational acceptance** — Still required before the event: the eight-hour bot-only soak and a full rehearsal on the actual router with representative laptops. `scripts/smoke_match.py` passed against a local stack on 2026-10-18. Evidence: `docs/event-runbook.md`, `checklist.md`. Last verified: 2026-10-18.
