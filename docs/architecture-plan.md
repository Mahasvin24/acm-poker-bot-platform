# Headless Tournament Architecture

Status: frozen v1 contract
Last reviewed: 2026-10-01

## Scope

Version 1 is a play-money, server-authoritative no-limit Texas Hold'em freezeout for
2–36 entrants at six-player tables. An entrant is either a human controlled through the
central application or a bot hosted by its owner on the event LAN. The first milestone is
headless: poker correctness, recovery, and bot isolation must pass before any Next.js client is
built. 3D rendering, spectators, chat, payouts, re-entry, rebuys, and polish are deferred.

## Runtime topology

```text
human/admin client ──HTTP──> FastAPI (exactly one worker)
                              ├── tournament coordinator
                              ├── one serialized coordinator per active table
                              ├── PokerEngine adapter ──> PokerKit 0.7.6
                              ├── bot gateway ──HTTP──> participant bot APIs
                              └── SQLAlchemy ──> PostgreSQL 17
```

PostgreSQL is the only durable authority. Redis is intentionally absent from v1. The process
may keep coordinator objects in memory, but every accepted action is committed as an immutable
action plus a complete private recovery snapshot before in-memory state advances. A database
failure therefore pauses the affected table rather than creating divergent state.

The deployment must use exactly one application worker. Adding another worker requires a new
cross-process ownership design and is not a supported tuning knob.

## Component boundaries

- `domain/` owns frozen commands, events, snapshots, versions, failure reasons, and tournament
  configuration. Chip values are integers; a raise is always `amount_to` for the current street.
- `engine/` contains the application-owned `PokerEngine` interface and the PokerKit adapter.
  PokerKit objects never cross this boundary. Recovery uses the stored deck and adapter state.
- `coordinator/` serializes commands for one table. It persists a pending decision before any
  bot call, never waits inside a database transaction, and commits exactly one action.
- `tournament/` owns seating, levels, breaks, balancing, table breaking, elimination order,
  pause boundaries, and completion. It emits deterministic `StartHandRequest` values.
- `bots/` owns the versioned wire contract, endpoint allowlisting, challenge verification,
  strict parsing, deadlines, and failure-to-fallback conversion.
- `auth/` owns Argon2id accounts, hashed sessions, entrant ownership, roles, and encrypted bot
  tokens. Admin rights are explicit; no email address is magical.
- `integration/` joins account entrants, tournaments, table coordinators, bots, and safe player
  projections without weakening the boundaries above.
- `api/` is a transport layer. It never calculates poker legality and never serializes private
  recovery snapshots.

## Durable write and recovery rules

For a player decision, the coordinator first commits a `pending_decision` containing the acting
seat, legal actions, table version, and UTC deadline. A human response or the single bot request
is processed outside a database transaction. The accepted action, emitted events, next private
snapshot, table version increment, and pending-decision resolution are committed atomically.

On restart, a table is reconstructed from its last snapshot. If a pending decision survived the
crash, it is not reissued to the bot: the coordinator records the deterministic fallback (check
when legal, otherwise fold) with `restart_recovery`. A failure after commit but before client
notification is harmless because clients resync from the stored version.

Snapshots contain the full deck order and engine recovery state. Those fields are server-only.
Player views are allowlisted and may reveal only that player's hole cards plus public cards and
public action history.

## Tournament rules

The baseline is the 2026 Poker TDA rules with these fixed house choices:

- Six seats per table and at most 36 entrants; one entrant per account per tournament.
- Big-blind ante equals the big blind. The big blind is taken first, then the ante from the
  remaining stack.
- Blinds change only for new hands. Heads-up uses button/small-blind, first action preflop, and
  last action postflop.
- Incomplete all-in raises and reopening follow the pinned adapter tests.
- Each side pot is split independently. Its odd chip goes to the first winning seat left of the
  button.
- All live hands are exposed at an all-in showdown; otherwise only cards needed to establish a
  winning or tied hand become public.
- Simultaneous bust-outs are ordered by start-of-hand stack; equal stacks tie.
- Tables balance only between hands, moving next-big-blind to the worst legal position. The
  shortest removable table breaks first; ties use highest table ID and seeded assignment.
- Disconnects do not stop a decision clock. Administrative pause waits for current hands and
  freezes the level clock.

The default is 20,000 chips, 15-minute levels, and a five-minute break after every fourth level.
The canonical blind schedule lives in `domain/tournament.py`; it uses the smooth 100/200 through
75,000/150,000 progression published for a 20,000-chip WSOP Circuit event, then doubles all
amounts after its final row if play somehow continues. Tournament settings are mutable only in
draft state.

## Bot protocol v1

Bots implement fixed `GET /v1/health`, `POST /v1/verify`, and `POST /v1/action` endpoints. The
platform accepts a numeric LAN IP and bounded port, constructs the URL, and rejects hostnames,
redirects, proxies, loopback, link-local, multicast, tournament infrastructure, and addresses
outside `POKER_PARTICIPANT_SUBNET`.

Registration displays a random bearer token once and stores it encrypted under
`POKER_SECRET_KEY`. Verification authenticates that token and echoes a short-lived challenge.
Live action calls use a 500 ms connect timeout, a three-second total decision deadline, no
redirect, proxy, or retry, a 64 KiB request ceiling, and a 4 KiB response ceiling.

All JSON objects reject extra properties, duplicate keys, unsupported protocol versions,
non-integer chip values, stale identifiers, wrong content types, illegal actions, and late
responses. Every failure becomes one recorded fallback and cannot stop the table. The public
schemas are in `schemas/`; starter bots and conformance instructions are in `examples/bots/`.

Direct HTTP on the trusted club LAN is an explicit v1 tradeoff. Bot TLS, signatures, pinning,
anti-collusion, and casino-grade controls are out of scope.

## Deployment and operations

- Run PostgreSQL and the application on the event machine; prefer wiring the server to the AP.
- Set a stable server address, a unique 32+ character secret, the actual participant subnet,
  router/server addresses in `POKER_BLOCKED_IPS`, and the browser origin.
- Run `alembic upgrade head`, bootstrap the admin explicitly, and start one Uvicorn worker.
- Plain HTTP is acceptable on the trusted event LAN if local certificate provisioning threatens
  rehearsal reliability. Set secure cookies only when the central application is HTTPS.
- Use the runbook in `docs/event-runbook.md` on the actual router and representative bot laptops.

## Acceptance gates

The automated suite must cover heads-up order, button movement, minimum/under raises, reopening,
side pots, ties, odd chips, short-stack BBA, showdown, elimination order, seating, balancing,
breaking, and heads-up transition. Property tests execute at least 10,000 generated hands and
check chip/card/state/version/replay invariants.

Recovery tests cover termination before dispatch, during the bot call, after response and before
commit, and after commit before notification. The milestone also requires 100 seeded 36-player
tournaments, an eight-hour six-table soak, and a dress rehearsal on event-equivalent hardware.
Those hardware/time gates are operational acceptance activities, not facts established by the
unit test suite.
