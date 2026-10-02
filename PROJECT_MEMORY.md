# Project Memory

## Constraints and invariants

- **Event environment** — The tournament is intended to run with participants on the same Wi-Fi. Bot entrants host their own APIs at registered IP addresses and ports. Network reachability on the actual AP remains to be proven. Evidence: user requirements and `docs/architecture-plan.md`. Last verified: 2026-10-01.
- **Reliability before presentation** — Correct poker logic, strict bot isolation, edge-case testing, and event resilience take priority over UI polish. A 3D table is explicitly deferred until the functional flow is stable. Evidence: user requirements and `docs/architecture-plan.md`. Last verified: 2026-10-01.
- **Entrant types** — The platform must support both human entrants with a playable web interface and bot entrants driven through an external API, plus an administrator who controls tournaments. Evidence: user requirements. Last verified: 2026-10-01.
- **Bot development support** — A public bot protocol and a way for participants to test their bots are required parts of the product, not optional tooling. Evidence: user requirements. Last verified: 2026-10-01.

## Discoveries and gotchas

- **Greenfield repository** — The repository had no tracked files or commits when architecture planning began. Evidence: `git status --short --branch` on 2026-10-01.
- **Redis boundary** — The current proposal does not treat Redis as the sole source of truth or expose it to browsers. PostgreSQL owns durable tournament state; Redis is proposed for cache/live fan-out. Rationale and sources: `docs/architecture-plan.md`.

## Open threads

- **Architecture proposal is not yet accepted** — Review and decide the open product/rules/network questions in `docs/architecture-plan.md` before implementation.
- **Poker engine selection** — PokerKit is the leading candidate but must pass the adapter spike listed in `docs/architecture-plan.md` before adoption.
- **LAN bot transport** — Direct HTTP to registered IP/port must be rehearsed on the actual access point. An outbound persistent bot connection is the fallback if peer connectivity is unreliable.
