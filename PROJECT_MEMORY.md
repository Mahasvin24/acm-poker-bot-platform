# Project Memory

## Constraints and invariants

- **Event environment** — The tournament is intended to run with participants on the same Wi-Fi. Bot entrants host their own APIs at registered IP addresses and ports. Network reachability on the actual AP remains to be proven. Evidence: user requirements and `docs/architecture-plan.md`. Last verified: 2026-10-01.
- **Reliability before presentation** — Correct poker logic, strict bot isolation, edge-case testing, and event resilience take priority over UI polish. A 3D table is explicitly deferred until the functional flow is stable. Evidence: user requirements and `docs/architecture-plan.md`. Last verified: 2026-10-01.
- **Entrant types** — The platform must support both human entrants with a playable web interface and bot entrants driven through an external API, plus an administrator who controls tournaments. Evidence: user requirements. Last verified: 2026-10-01.
- **Bot development support** — A public bot protocol and a way for participants to test their bots are required parts of the product, not optional tooling. Evidence: user requirements. Last verified: 2026-10-01.
- **Frontend account and tournament flow** — The production Next.js App Router workspace lives in `frontend/`. `/account`, `/dashboard`, `/admin`, `/bot-guide`, and `/play/[tournamentId]` now cover account access, invite-based joining, human/bot registration, bot verification, tournament control, and player-safe gameplay. 3D rendering remains deferred. Evidence: `frontend/src/app/`, `frontend/src/features/account/`, `frontend/src/features/table/poker-table.tsx`. Last verified: 2026-10-02.

## Discoveries and gotchas

- **Greenfield repository** — The repository had no tracked files or commits when architecture planning began. Evidence: `git status --short --branch` on 2026-10-01.
- **Single-process authority** — PostgreSQL is the durable authority and the v1 app must use exactly one FastAPI worker. Redis is excluded unless a later multi-process design is approved. Evidence: `docs/architecture-plan.md`, `src/poker_bot_platform/config.py`. Last verified: 2026-10-01.
- **PostgreSQL table creation ordering** — Table models intentionally have no ORM relationships, so `SqlAlchemyTableRepository.create_table` must flush the parent `poker_tables` row before adding the snapshot and domain events. The live PostgreSQL repository test covers this foreign-key ordering and passed against a fresh `_test` database. Evidence: `src/poker_bot_platform/persistence/sqlalchemy.py`, `tests/coordinator/test_postgres_repository.py`. Last verified: 2026-10-02.
- **Human table API projection** — Player table state includes explicit `viewer_seat` and `acting_seat` fields. The frontend uses these identifiers to orient the six-seat layout and must never infer either identity from player names. Evidence: `src/poker_bot_platform/api/models.py`, `src/poker_bot_platform/integration/runtime.py`, `frontend/src/features/table/types.ts`. Last verified: 2026-10-02.
- **Bot failure semantics** — Every bot protocol or transport failure produces exactly one durable automatic check-or-fold, clears the pending decision, and records a specific `FailureReason`; another player's private cards and recovery-only state never enter the bot request. Evidence: `src/poker_bot_platform/bots/`, `src/poker_bot_platform/coordinator/service.py`, `tests/integration/test_mixed_hand.py`. Last verified: 2026-10-02.

## Open threads

- **External acceptance gates** — Local PostgreSQL and browser acceptance now cover the complete two-player human/starter-bot flow. The eight-hour soak and full actual-router/event-Wi-Fi rehearsal remain required before event readiness. Evidence: `docs/event-runbook.md`. Last verified: 2026-10-02.
