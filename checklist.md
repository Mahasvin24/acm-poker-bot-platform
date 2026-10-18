# Platform Audit Checklist

Rubric for evaluating the ACM Poker Bot Platform end to end. Each item is graded
**Pass**, **Partial**, **Fail**, or **Untested**. Each item names how to verify it. The
methods are code review, automated tests, a manual browser walkthrough, or a chaos drill
(deliberately breaking something during live play).

Items marked *Initial note* already have evidence from the first exploration. They still
need confirming during grading.

Baseline at audit start (commit `99d50fd`): 121 backend tests pass and 2 Postgres-only tests
are skipped. `tsc --noEmit` and `eslint` are clean. One demo test is flaky (see 3.1.6).

---

## 1. Account creation: users and bots

### 1.1 Human accounts
- [ ] **1.1.1** A new user can create an account at `/account`, gets signed in, and lands on the right page (user goes to `/dashboard`, admin goes to `/admin`). *Verify: browser.*
- [ ] **1.1.2** Validation errors are clear and appear inline: bad email, password under 10 characters, mismatched confirmation, duplicate email. *Verify: browser + `tests/auth`.*
- [ ] **1.1.3** Passwords are hashed with Argon2id, sessions are stored only as hashes, and the cookie is `HttpOnly` and `SameSite=Lax`. *Verify: code review of `auth/service.py` and `api/router.py`.*
- [ ] **1.1.4** Sign-out revokes the session on the server and later API calls return 401. *Verify: test + browser.*
- [ ] **1.1.5** Login has brute-force protection (rate limit or backoff). *Initial note: no rate limiting found anywhere in `src/`.*
- [ ] **1.1.6** Users can see and change their display identity. There is a way to recover from a forgotten password, even if it's only an admin reset. *Initial note: no profile, password reset, or admin account management exists.*
- [ ] **1.1.7** The first admin is created explicitly (`poker-platform bootstrap-admin`), and no route lets a user promote themselves. *Verify: code review.*

### 1.2 Bot accounts and identity
- [ ] **1.2.1** Bot registration makes sense to a first-time bot builder: register an entry, enter IP and port, get a one-time token, verify, and see "Verified". *Verify: browser walkthrough with `examples/bots/python`.*
- [ ] **1.2.2** The bearer token is shown once, can be copied, is stored encrypted, and is never returned again. Replacing the endpoint issues a new token. *Verify: code review + browser.*
- [ ] **1.2.3** Endpoint validation rejects loopback, link-local, multicast, blocked infrastructure IPs, hostnames, and anything outside `POKER_PARTICIPANT_SUBNET`, with an understandable error message. *Verify: `tests/bots` + manual.*
- [ ] **1.2.4** Verification failures say what went wrong in plain terms (timeout, wrong token, bad JSON, wrong content type), not just the raw `FailureReason`. *Verify: browser with a deliberately broken bot.*
- [ ] **1.2.5** A bot has an identity that lasts beyond one event, so the same bot can enter another match without re-registering and re-verifying from scratch. *Initial note: a bot exists only as a per-tournament entrant. Each tournament needs a new entry, a new token, and a new verification.*
- [ ] **1.2.6** One person can own both a human entry and a bot entry, or run several bots, if the event wants that. *Initial note: the limit is one entrant per account per tournament, so a builder who also wants to play needs two accounts.*
- [ ] **1.2.7** Bot builders can test against a sandbox without an admin running a tournament: conformance client, health check, and a practice hand against house bots. *Initial note: there's a CLI conformance client (`bots/conformance.py`) but no self-serve practice match in the UI.*
- [ ] **1.2.8** The `/bot-guide` page and `examples/bots/README.md` match the real schemas in `schemas/` and the Pydantic models in `bots/models.py`. *Verify: code review, field by field.*

---

## 2. Creating a match and inviting players

### 2.1 Match creation (admin)
- [ ] **2.1.1** An admin can create a single match (one table, two to six seats) without the full tournament machinery: blind levels, breaks, balancing. *Initial note: only tournaments exist. Creating one means picking a free-text ID, then Open Registration → Seat Entrants → Start.*
- [ ] **2.1.2** Match settings are understandable and limited to what matters: seat count, starting stack, blinds, human clock, and whether blinds escalate. *Verify: browser.*
- [ ] **2.1.3** The admin sees a live roster: who joined, human or bot, bot verification status, and connection or last-seen status. *Initial note: the admin dashboard shows counts only. There's no entrant list and no auto-refresh; the admin clicks "Refresh State".*
- [ ] **2.1.4** The admin can remove or kick an entrant, re-open a seat, cancel or end a match, and start a rematch. *Initial note: none of these commands exist.*
- [ ] **2.1.5** The admin can watch a live match as a spectator, without seeing hole cards. *Initial note: no spectator or admin table view exists.*
- [ ] **2.1.6** The admin can list existing matches and tournaments instead of remembering IDs. *Initial note: there's no list endpoint; the admin must type the ID.*

### 2.2 Invitations and joining by code
- [ ] **2.2.1** Creating a match generates a short, human-friendly join code, for example `K7Q-4PM`: no ambiguous characters, case-insensitive, unguessable enough for a LAN event. *Initial note: not implemented. The closest thing is an invite link containing the raw tournament ID.*
- [ ] **2.2.2** A user enters the code in a single obvious field (landing page or dashboard), picks Human or Bot, picks a display name, and is placed in the lobby. *Verify: browser.*
- [ ] **2.2.3** The join code works for bots too: the builder enters the code, then IP, port, and verification. *Verify: browser.*
- [ ] **2.2.4** Error states are clear: invalid code, match full, match already started, already joined, code expired or revoked. *Verify: browser + API tests.*
- [ ] **2.2.5** The admin can regenerate or revoke a code and lock the lobby. *Verify: API.*
- [ ] **2.2.6** Joined players see a lobby or waiting room that updates live (seat list, "waiting for host to start") and automatically opens the table when play begins. *Initial note: before seating, `/play/{id}` returns 404 and the frontend stops polling on 4xx, so the player must click "Try Again".*
- [ ] **2.2.7** Invite and join links survive sign-up and sign-in. The `?tournament=` query string is already carried through; check the same for codes. *Verify: browser.*

---

## 3. Human gameplay

### 3.1 Poker correctness
- [ ] **3.1.1** The engine is a trusted, pinned library. *Initial note: PokerKit 0.7.6 is pinned and wrapped behind `engine/pokerkit_adapter.py`; its objects never cross the boundary. Confirm PokerKit's maintenance status and any known issues in 0.7.6.*
- [ ] **3.1.2** Betting order is correct: heads-up blinds and action order, button movement, dead-button handling after eliminations. *Verify: `tests/engine` + a seeded multi-hand replay.*
- [ ] **3.1.3** Minimum raise, short all-in (incomplete raise), and action re-opening rules match house rules. Raise bounds never come back with min above max. *Verify: tests + targeted cases.*
- [ ] **3.1.4** Side pots, split pots, and odd chips (first winner left of the button) are correct. *Verify: tests + replay with three or more all-ins.*
- [ ] **3.1.5** Big-blind ante with a short-stacked big blind (blind first, then ante) is correct. *Verify: tests.*
- [ ] **3.1.6** Showdown reveals only what the rules allow: every live hand in an all-in showdown, otherwise only hands needed to win or tie. Mucked hands stay private. *Initial note: likely Fail. `integration/presentation.py::natural_hand_result` builds `revealed_hands` from every live seat's private `hole_cards`, not PokerKit's `public_hole_cards`. The first test run hit this: `test_demo_match_can_play_through_to_a_natural_result` failed with revealed seats `{1, 2}` versus visible live seats `{1}`. The test is flaky because the demo deck is random.*
- [ ] **3.1.7** The winner label, hand-strength label, and best five cards match the engine's pot awards in every case, including side-pot winners with weaker hands. *Verify: tests.*
- [ ] **3.1.8** Chips are conserved across every hand and the whole tournament, with no drift. *Verify: the 10,000-example Hypothesis property test exists for fold-outs. Check whether showdowns and all-ins are covered too.*
- [ ] **3.1.9** The shuffle is fair and its seed stays secret. *Initial note: `random.Random` is seeded from SHA-256 of a 256-bit `secrets` seed plus a per-hand purpose string. Confirm `seed_hex` never appears in any API response or log.*

### 3.2 Pacing: can a human keep up?
- [ ] **3.2.1** At a real tournament table, consecutive bot actions are paced on the client or the server so a human can follow each one. *Initial note: likely Fail. Only the ephemeral demo paces bots. In production, bots answer in milliseconds and the frontend polls every 500 ms, so several actions, or a whole street, can land between frames. The UI narrates only the latest action.*
- [ ] **3.2.2** Street changes (flop, turn, river) get a deliberate pause before the next decision. *Initial note: there's a client-side reveal animation (about 0.5–1 s), but the server doesn't wait.*
- [ ] **3.2.3** The human's decision clock doesn't start while their screen is still showing the previous hand's result or dealing animation. *Initial note: likely Fail. The frontend holds the result for 4 s, but the server opens the next decision immediately, so the human can lose about 4 s or more of their 30 s.*
- [ ] **3.2.4** The countdown bar is accurate for both human and bot turns. *Initial note: Fail. `PublicTurnResponse.duration_ms` always uses the human timeout, so a 3 s bot turn shows as 10% of a 30 s bar. The frontend also hardcodes 30,000 ms in `turnFor`.*
- [ ] **3.2.5** The default human clock of 30 s, and any time bank, is appropriate for novices. *Verify: playtest.*
- [ ] **3.2.6** At showdown, there's enough time to read the revealed hands and the result before the next deal. *Verify: playtest.*

### 3.3 UX and comprehension
- [ ] **3.3.1** It's always obvious whose turn it is, what the player can do, how much it costs to call, and what the pot is. *Verify: browser.*
- [ ] **3.3.2** Action labels follow poker convention: Bet versus Raise, Check versus Call, All-in when the raise equals the stack. *Initial note: the button always says "Raise" and the field says "Raise to", even when opening the betting.*
- [ ] **3.3.3** Bet-sizing presets (½ pot, ¾ pot, pot) compute the right raise-to amount and clamp to legal bounds. *Verify: unit test of `RaiseControl` math against `pot` semantics.*
- [ ] **3.3.4** Chip units fit a play-money event. *Initial note: stacks are formatted as USD (`$20,000`), which may read as real money.*
- [ ] **3.3.5** Tournament or match context is visible at the table: level, time left, next blinds, players remaining, break or pause status. *Initial note: `tournament_status` and `table_status` reach the client but are never rendered, so breaks, pauses, and quarantines look like a frozen table.*
- [ ] **3.3.6** Eliminated players see a clear "You finished Nth" screen with standings. *Initial note: Fail. Once eliminated, the API returns 404 and the UI shows "Waiting for a seat", then stops polling.*
- [ ] **3.3.7** A finished match shows the winner and final standings to everyone. *Verify: browser.*
- [ ] **3.3.8** Automatic actions (timeouts, bot fallbacks) are visible and explained without being noisy. *Verify: browser.*
- [ ] **3.3.9** Optional keyboard shortcuts work, with safeguards against accidental folds. *Verify: browser.*
- [ ] **3.3.10** Previous-hand review or a hand-history replay exists. *Verify: browser.*
- [ ] **3.3.11** The layout works for two to six players and at laptop, tablet, and phone widths. *Verify: browser at 1440, 1024, 768, and 390 px.*
- [ ] **3.3.12** Accessibility: the board and cards have aria labels, focus order is sensible, contrast is sufficient, and reduced motion is respected. *Verify: browser + an audit tool.*

---

## 4. Bot gameplay and the wire contract

### 4.1 Request structure (platform to bot)
- [ ] **4.1.1** `POST /v1/action` requests validate against `schemas/bot-action-request-v1.schema.json`, and the schema matches `bots/models.py` exactly. *Verify: contract test (`tests/test_contracts.py`) + schema diff.*
- [ ] **4.1.2** The request has everything a reasonable strategy needs: hole cards, board, pot, side pots, stacks, per-street and per-hand commitments, button, blinds and ante, legal actions with call amount and raise bounds, full action history with seats and streets, and the deadline. *Initial note: the action history has no street marker per action, so a bot must reconstruct street boundaries itself.*
- [ ] **4.1.3** Bots learn how hands end: showdown cards, winners, and final stacks, for example through a hand-result notification or the next request. *Initial note: bots get only action requests and never see results or opponents' shown cards.*
- [ ] **4.1.4** Bots get tournament or match context: level, blinds schedule, players remaining, hand number. *Initial note: only current blinds are sent.*
- [ ] **4.1.5** No private information leaks: no other players' hole cards, deck order, engine state, or seed. *Verify: code review of `bots/factory.py` + test.*
- [ ] **4.1.6** Identifiers and versions are stable and documented (`decision_id`, `table_version`, `hand_id`), and bots can tell whether they're acting on a stale decision. *Verify: docs + tests.*
- [ ] **4.1.7** Integer chip values only, ISO-8601 UTC deadlines, consistent naming (`amount` versus `amount_to`), and enum values documented. *Verify: schema review.*
- [ ] **4.1.8** Request size stays within the 64 KiB limit even for a long hand history. *Verify: test with a worst-case hand.*

### 4.2 Response handling (bot to platform)
- [ ] **4.2.1** Strict parsing: extra fields, duplicate keys, numeric strings, booleans used as integers, wrong protocol, and wrong content type are all rejected with a specific `FailureReason`. *Verify: `tests/bots/test_gateway.py`.*
- [ ] **4.2.2** Mismatched identifiers (stale tournament, table, hand, decision, or version) produce `stale`. Illegal actions and out-of-range raises produce `illegal_action`. *Verify: tests.*
- [ ] **4.2.3** Bot builders can see their own failure log (reason, hand, and time) to debug. *Initial note: failure reasons are stored per action and shown on the table, but there's no bot-facing diagnostics view.*
- [ ] **4.2.4** The 3 s deadline is measured on the server, and docs warn builders about clock skew on bot machines. *Verify: docs.*

### 4.3 Sample bots and docs
- [ ] **4.3.1** The Python and JavaScript starter bots run as documented and pass the conformance client. *Verify: run both.*
- [ ] **4.3.2** The guide includes a full worked request/response example and a "common mistakes" section. *Verify: read `/bot-guide`.*

---

## 5. Reliability and security

### 5.1 Bot faults
- [ ] **5.1.1** Each bot failure produces exactly one durable automatic check or fold and the table keeps going. Covered cases: no response, slow response, connection refused, HTTP 5xx, malformed JSON, oversized body, wrong content type, illegal action, stale identifiers, process death mid-request. *Verify: `tests/integration/test_mixed_hand.py` + chaos drill.*
- [ ] **5.1.2** A bot that fails repeatedly is handled without wasting 3 s per action forever. For example: mark it "unresponsive" after N failures, shorten its wait, alert the admin. *Initial note: every failure waits for the full timeout, so a dead bot costs 3 s on every decision.*
- [ ] **5.1.3** Network requests can't be redirected or proxied to internal targets (SSRF). *Initial note: `follow_redirects=False`, `trust_env=False`, numeric IP validation, and a subnet allowlist are all in place.*

### 5.2 Human faults
- [ ] **5.2.1** A human who closes the tab or loses Wi-Fi is auto-checked or folded when their deadline passes, and the table doesn't wait longer than the clock. *Initial note: deadlines are enforced by `GameplayScheduler` every 250 ms, independent of client polling.*
- [ ] **5.2.2** Repeatedly absent humans are marked "away" or "sitting out" (visible to others) and stop costing a full 30 s per decision. *Initial note: no away state exists; an absent player costs a full clock on every hand.*
- [ ] **5.2.3** Reconnecting restores the exact current state, including a pending decision with the correct remaining time. *Verify: browser drill.*
- [ ] **5.2.4** A double submit, a stale `decision_id`, or a race between timeout and click resolves to exactly one action, and the UI resyncs cleanly. *Verify: tests + manual double-click.*
- [ ] **5.2.5** Multiple tabs for the same player behave consistently. *Initial note: terminal hand views are popped once per entrant, so a second tab may skip the result display.*

### 5.3 Server faults
- [ ] **5.3.1** Process restart: the table restores from its snapshot, an interrupted decision gets exactly one `restart_recovery` fallback, and nothing is duplicated. *Verify: `tests/coordinator/test_lifecycle.py` + live kill drill.*
- [ ] **5.3.2** A temporary database outage pauses affected tables and they recover on their own once the database is back. *Initial note: likely Fail. `TableCoordinator` sets `_database_paused` and the runtime caches the coordinator forever; `restore()` only runs when a coordinator is first created, so a table stays stuck until the process restarts.*
- [ ] **5.3.3** An engine invariant failure quarantines only the affected table, and the admin and players are told. *Initial note: quarantine works on the backend, but the UI never renders `table_status`.*
- [ ] **5.3.4** One slow bot can't stall other players' state reads or other tables. *Initial note: likely Fail. `player_state` and `submit_human_action` hold the per-tournament lock while driving every table, including bot HTTP calls of up to 3 s each, so a human's poll or click can block for several seconds.*
- [ ] **5.3.5** The scheduler loop survives exceptions per tournament and logs them with context. *Verify: code review of `integration/scheduler.py`.*
- [ ] **5.3.6** API errors return consistent JSON (`detail`), never stack traces. Unexpected exceptions return 500 with a safe message. *Verify: fuzz the endpoints.*

### 5.4 Security
- [ ] **5.4.1** The app refuses to start with the default `POKER_SECRET_KEY`. *Initial note: Fail. `config.py` ships a default of `development-only-change-before-event` and accepts it.*
- [ ] **5.4.2** CSRF: every state-changing route requires a matching `Origin` (`SameOriginGuard`). *Verify: test each mutation route.*
- [ ] **5.4.3** Authorization: users can only act for their own seat, only admins reach admin routes, and bots can't use human endpoints. *Verify: tests.*
- [ ] **5.4.4** Demo endpoints can't disrupt real play or other users. *Initial note: `/api/v1/demo-human-versus-bot` is one global, unauthenticated match. Anyone on the LAN can start, end, or `cheat/{outcome}` it for everyone.*
- [ ] **5.4.5** Input limits: display names, IDs, and request body sizes are bounded, and no endpoint can be used to exhaust memory. *Verify: code review.*
- [ ] **5.4.6** Secrets and tokens never appear in logs. *Verify: grep the logging calls + a log review during a drill.*

### 5.5 Operational readiness
- [ ] **5.5.1** The eight-hour soak and the multi-table seeded tournament rehearsal from `docs/event-runbook.md` have been run. *Initial note: listed as an open thread in `PROJECT_MEMORY.md`.*
- [ ] **5.5.2** The live Postgres tests run in CI or at least before each release. *Initial note: two tests are skipped without `POKER_TEST_DATABASE_URL`.*
- [ ] **5.5.3** Structured logs and a basic admin health view exist: active tables, failures per bot, stuck-table detection. *Verify: code review.*

---

## 6. UI quality and performance

- [ ] **6.1** Visual consistency across landing, account, dashboard, admin, play, and bot-guide: the same type, spacing, buttons, and status pills. *Verify: browser screenshots.*
- [ ] **6.2** The table renders smoothly: no layout shift when cards or chips change, no flicker between polls, and animations don't stack up when several updates arrive together. *Verify: browser + performance profile.*
- [ ] **6.3** Real-time transport has acceptable latency and load. *Initial note: HTTP polling every 500 ms during turns and 1.2 s otherwise, plus a 200 ms re-render tick for the clock. Measure CPU and network with six humans, and consider SSE or WebSocket.*
- [ ] **6.4** Loading, empty, and error states exist for every page, with retry. The table currently stops retrying on 4xx. *Verify: browser with the API down, the database down, and a 404.*
- [ ] **6.5** Navigation is clear: a signed-in user always knows how to get to their table, lobby, or bot setup, and how to leave. *Verify: browser.*
- [ ] **6.6** No console errors, React warnings, or hydration mismatches. *Verify: browser devtools on each route.*
- [ ] **6.7** The production build (`next build`) succeeds, and Lighthouse performance and accessibility are reasonable on `/`, `/play/demo`, and `/dashboard`. *Verify: build + Lighthouse.*
- [ ] **6.8** Leftover or unused surfaces are removed or clearly labeled: `design-mockups/`, `/play/demo` preview mode, and the misspelled `/demo-human-verus-bot` route. *Verify: review.*

---

## 7. Cross-cutting

- [ ] **7.1** The README and setup docs get a new contributor from clone to a playable match in under 15 minutes. *Verify: follow `docs/setup.md` from a clean checkout.*
- [ ] **7.2** There's an end-to-end test that covers create match → join (human and bot) → play hands → finish, ideally browser-driven. *Initial note: backend integration tests exist; there are no frontend or E2E tests.*
- [ ] **7.3** `PROJECT_MEMORY.md` and `docs/architecture-plan.md` match the code after the changes. *Verify: review.*
