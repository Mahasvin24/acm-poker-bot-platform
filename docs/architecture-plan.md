# Match Platform Architecture

Status: v2 (code-joined matches)
Last reviewed: 2026-10-18

## Scope

The platform runs play-money, server-authoritative no-limit Texas Hold'em **matches**: one table
of two to six seats, created by an administrator and joined with a short code. A seat is held by
a human playing in the browser or by a participant-hosted bot. Tournaments (levels as phases,
breaks, multi-table balancing) were removed in v2; a match can still escalate blinds on a timer.
3D rendering, chat, payouts, re-entry, and rebuys remain out of scope.

## Runtime topology

```text
browser ──HTTP──> Next.js (/api/v1 proxy) ──> FastAPI (exactly one worker)
                                              ├── MatchRegistry + MatchCoordinator (per match)
                                              ├── GameplayScheduler ──> MatchRuntime.drive
                                              │     └── TableCoordinator ──> PokerKit 0.7.6
                                              ├── BotGateway ──HTTP──> participant bot APIs
                                              └── SQLAlchemy ──> PostgreSQL 17
```

PostgreSQL is the only durable authority. The process keeps coordinator objects in memory, but
every accepted action is committed as an immutable action plus a complete private recovery
snapshot before in-memory state advances. Exactly one application worker is supported.

## Component boundaries

- `domain/` owns frozen commands, events, snapshots, `MatchConfig`, and blind levels. Chip values
  are integers; a raise is always `amount_to` for the current street. Every recorded action
  carries its street.
- `engine/` contains the `PokerEngine` interface and the PokerKit adapter. PokerKit objects never
  cross this boundary.
- `coordinator/` serializes commands for one table. It persists a pending decision before any
  bot call, never waits inside a database transaction, and commits exactly one action.
- `match/` owns the match state machine (lobby, running, pause requested, paused, completed,
  cancelled), join codes, seating, elimination standings, and blind-level ticks. It emits
  deterministic `StartHandRequest` values. State is stored as one JSONB document per match with a
  unique partial index on the active join code.
- `bots/` owns the versioned wire contract (`poker-bot.v2`), schema generation, endpoint
  allowlisting, verification, strict parsing, deadlines, and failure explanations.
- `auth/` owns Argon2id accounts, hashed revocable sessions, roles, password reset, and reusable
  bot profiles whose bearer tokens are encrypted under `POKER_SECRET_KEY`.
- `integration/` joins matches, tables, bots, and per-viewer projections: `MatchService` for
  commands and views, `MatchRuntime` for driving tables, `GameplayScheduler` for timing.
- `api/` is a transport layer. It never calculates poker legality and never serializes private
  recovery snapshots.

## Driving tables

Only the scheduler drives tables. Every 250 ms (or immediately when woken by a command) it
starts one background drive per running match, skipping a match whose previous drive is still
in progress. Reads never take the drive lock, so a bot request in flight cannot delay another
player's poll. Human actions are applied directly under the table coordinator's lock.

**Pacing.** At tables with a seated human the runtime pauses 3 s after a deal, 1.5 s after an
action, 2.5 s after a street change, and 5 s after a hand before dealing the next. A human's
decision clock opens only after the pause ends. Bots never see these pauses; bot-only tables run
at full speed.

**Absent humans.** After two consecutive timeouts a human is marked away (visible to everyone)
and receives a 5 s clock until they act again.

**Failing bots.** After three consecutive connection, timeout, or HTTP failures, each decision
first probes `/v1/health` with a 500 ms budget and records an immediate fallback if the bot is
still down. One successful action resets the breaker. Per-bot decision logs with latency and
failure explanations are kept in memory for owner diagnostics and the admin roster.

## Durable write and recovery rules

For a player decision, the coordinator first commits a `pending_decision` containing the acting
seat, legal actions, table version, and UTC deadline. The accepted action, emitted events, next
private snapshot, table version increment, and pending-decision resolution are committed
atomically.

On restart, a table is reconstructed from its last snapshot. A pending decision that survived is
not reissued: the coordinator records the deterministic fallback (check when legal, otherwise
fold) with `restart_recovery`. The same path handles a database failure during play: the paused
coordinator is evicted and restored from durable state with exponential backoff (1 s to 30 s).

Snapshots contain the full deck order and engine recovery state. Player views are allowlisted
and reveal only the viewer's hole cards plus cards PokerKit actually showed; mucked losing hands
stay private in table views, hand results, and the bot `previous_hand` summary.

## Match rules

- Two to six seats; an account may hold one human seat and any number of bot seats per match;
  a bot profile may hold one seat per match. Seats are spread evenly around the table.
- Default 20,000 chips with 100/200 fixed blinds. Optional big-blind ante. Optional escalation
  scales the opening blinds along the smooth WSOP Circuit progression every N minutes; new blinds
  apply from the next hand.
- Heads-up uses button/small-blind, first action preflop, last action postflop. Side pots are
  split independently; odd chips go to the first winning seat left of the button.
- Simultaneous bust-outs are ordered by start-of-hand stack; equal stacks tie.
- Pause and end take effect after the current hand. Ending ranks remaining players by chips.
  Cancelling abandons the current hand and keeps no standings. Join codes are released when a
  match completes or is cancelled.

## Bot protocol v2

Bots implement `GET /v1/health`, `POST /v1/verify`, and `POST /v1/action`. The platform accepts a
numeric LAN IP and bounded port and rejects hostnames, redirects, proxies, loopback, link-local,
multicast, event infrastructure, and addresses outside `POKER_PARTICIPANT_SUBNET`.

Action requests include the public table, the acting player's hole cards, legal actions, the
current hand's action history with streets, match context (hand number, level, players
remaining, next blinds), and a public summary of the previous hand. Live calls use a 500 ms
connect timeout, a three-second decision deadline, no retry, a 64 KiB request ceiling, and a
4 KiB response ceiling. All JSON objects reject extra properties, duplicate keys, wrong protocol
versions, non-integer chip values, stale identifiers, wrong content types, and illegal actions.
The schemas in `schemas/` are generated from the models by
`python -m poker_bot_platform.bots.schemas` and checked by the test suite.

## Security

- Placeholder or low-entropy `POKER_SECRET_KEY` values stop the server at startup.
- Login is rate-limited per client and per email; join-code lookups are limited per account.
- Every state-changing route requires a same-origin `Origin` header.
- The demo match is per browser session, bounded in count and idle age, with no forcing route.

## Acceptance gates

The automated suite covers engine rules, coordinator recovery, match lifecycle, join codes,
pacing, away state, the bot breaker, database-failure recovery, non-blocking reads, API flows,
showdown privacy, and generated schemas; Postgres-backed tests run when
`POKER_TEST_DATABASE_URL` names a database ending in `_test`. `scripts/smoke_match.py` exercises
the full flow against a running deployment. The eight-hour soak and a rehearsal on the event
router remain operational gates.
