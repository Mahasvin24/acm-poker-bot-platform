# Project Memory

## Constraints and invariants

- **Event environment** — The tournament is intended to run with participants on the same Wi-Fi. Bot entrants host their own APIs at registered IP addresses and ports. Network reachability on the actual AP remains to be proven. Evidence: user requirements and `docs/architecture-plan.md`. Last verified: 2026-10-01.
- **Reliability before presentation** — Correct poker logic, strict bot isolation, edge-case testing, and event resilience take priority over UI polish. A 3D table is explicitly deferred until the functional flow is stable. Evidence: user requirements and `docs/architecture-plan.md`. Last verified: 2026-10-01.
- **Entrant types** — The platform must support both human entrants with a playable web interface and bot entrants driven through an external API, plus an administrator who controls tournaments. Evidence: user requirements. Last verified: 2026-10-01.
- **Bot development support** — A public bot protocol and a way for participants to test their bots are required parts of the product, not optional tooling. Evidence: user requirements. Last verified: 2026-10-01.
- **Frontend foundation** — The production Next.js App Router workspace lives in `frontend/`. Its root route uses the approved “Quiet Spectacle” landing-page direction, and `/play/[tournamentId]` provides a player-safe human table with server-advertised actions, reconnect polling, authoritative deadlines, and a standalone `/play/demo` state. Registration, bot setup, admin UI, and 3D rendering remain deferred. Evidence: `frontend/src/app/page.tsx`, `frontend/src/features/table/poker-table.tsx`, `frontend/README.md`. Last verified: 2026-10-02.

## Discoveries and gotchas

- **Greenfield repository** — The repository had no tracked files or commits when architecture planning began. Evidence: `git status --short --branch` on 2026-10-01.
- **Single-process authority** — PostgreSQL is the durable authority and the v1 app must use exactly one FastAPI worker. Redis is excluded unless a later multi-process design is approved. Evidence: `docs/architecture-plan.md`, `src/poker_bot_platform/config.py`. Last verified: 2026-10-01.
- **Local test environment** — Docker was not available during implementation, so optional live-PostgreSQL tests could not run locally; migration SQL rendering and repository semantics were tested without it. The live database tests and rehearsal remain mandatory before event acceptance. Evidence: `tests/auth/test_postgres_auth.py`, `tests/coordinator/test_postgres_repository.py`, `docs/event-runbook.md`. Last verified: 2026-10-01.
- **Human table API projection** — Player table state includes explicit `viewer_seat` and `acting_seat` fields. The frontend uses these identifiers to orient the six-seat layout and must never infer either identity from player names. Evidence: `src/poker_bot_platform/api/models.py`, `src/poker_bot_platform/integration/runtime.py`, `frontend/src/features/table/types.ts`. Last verified: 2026-10-02.

## Open threads

- **External acceptance gates** — Run the optional live-PostgreSQL tests, eight-hour soak, and full actual-router rehearsal before declaring event readiness. These require Docker/event hardware unavailable in the implementation environment. Evidence: `docs/event-runbook.md`. Last verified: 2026-10-01.
