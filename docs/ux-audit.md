# Platform UX audit

## Brief and constraints

Experienced poker players, primarily on laptops. Preserve ACM's identity, physical chip stacks,
forest felt and warm action/seat colors. Simplification means less repetition and clearer actions,
not removing the visual cues that make poker understandable. Keep a shared table renderer,
one server-controlled pace, and independent matches (up to three concurrent tables).
No tournament brackets, balancing, API redesign, or new framework.

## Findings and disposition

Audit begun 2026-11-11; final verification 2026-11-12. Locations below are repository relative.

| Severity | Screen / reproduction | Finding and impact | Resolution |
| --- | --- | --- | --- |
| High | `/play/demo`, 1280×720 | Tutorial/status rows and minimum table height push betting controls below the fold. | Fixed: compact frame, visible action dock, collapsible details. Both collapsed and expanded details fit at 1280×720. |
| High | Table presentation hook | Phase updates can cancel card-animation timers; new hands can retain old card counts. | Fixed: board reveals scoped to hand/card changes. Current cards show immediately for a live decision or reconnect. Reveals only run inside the server presentation window, with a polling margin. |
| High | Player transport | Stale controls remain usable after connection failure; conflict refresh bypasses snapshot ordering. | Fixed: resync gate, synchronous submission lock, monotonic snapshot selection, refresh on online/focus/visibility return. |
| High | Password help → dashboard | New human/bot accounts are directed to change their temporary password, but account utilities only render for legacy accounts. | Fixed: collapsed account and password tools available for all participants; expanding them grows the page. |
| Medium | Big blind's pre-flop turn | Checking is legal, so the UI incorrectly labels a raise as an opening bet. | Fixed: street-aware bet/raise labels, covered by a regression test. |
| Medium | Table seats | Tiny repeated labels obscure stacks and bets; private cards overlap name panels. | Fixed: readable cards and chip labels. Green stack/red contribution towers retained, with current-street commitment and cumulative contribution distinguished. |
| Medium | First visual iteration | Removing physical chips and seat colors made the table harder to read and visually flat. | Corrected following user review: restored physical stacks, forest felt, human/bot accents, patterned card backs and warm turn/raise accents. |
| Medium | Table status | Tutorial stages, header, dock and rail repeat instructions; continuous clock tenths distract. | Fixed: concise street/actor/whole-second clock, contextual details and per-seat action labels. |
| Medium | `/join` and join confirmation | Multiple-bot wording contradicts the one-bot limit; invalid-code error is verbose and does not return focus. | Fixed: accurate copy and input focus on invalid code. |
| Medium | Landing | “Until one stack remains” omits timed/hand-limited endings; bot setup uses obsolete “My Bots.” | Fixed: accurate match endings and dashboard destination, removed a redundant promotional section and chapter labels. |
| Medium | Account/dashboard | Promotional headings and tiny tracked uppercase controls obscure functional tasks. | Fixed: functional titles, readable labels, concise errors and clear loading states. |
| Medium | Organizer overview | Player invitations precede the match overview. | Fixed: tables first, with code/occupancy/status; active matches sort before finished matches. |
| Medium | Results | Custom dialog lacks modal focus handling; pot reads zero after settlement. | Fixed: native dialog, Escape dismissal and final-hand review; authoritative awarded chips shown after settlement. |
| Medium | Spectator navigation | Reusing a transport across match IDs risks retaining the previous table snapshot. | Fixed: table keyed by match ID and reveal mode. |
| Medium | Practice | Fixed utility menu covers the table details control; polling can overlap and regress state. | Fixed: dedicated utility row, sequential polling, ordered updates and submission lock. |
| Low | Practice | Engine/storage internals dominate the description and duplicate start controls. | Fixed: practical explanation and one start action. |
| Low | Account/management routes | Generic browser titles make multiple event tabs difficult to distinguish. | Fixed: route-specific titles. |

## Verification

- Frontend: **15 tests pass**, TypeScript check and ESLint pass, production build passes.
- Backend: **208 tests pass**, excluding the two suites that reset the PostgreSQL schema.
  Ruff passes for changed test files. No database schema changes were made.
- Baseline: 9 frontend tests passed. The original integration/match run had 72 passes and one
  lifecycle-test failure. Its assertion incorrectly expected a bot action after an organizer
  ended the match before the first deal. Corrected the assertion to explicitly expect no action
  in that branch; normal-play coverage still requires bot actions. Production behavior unchanged.
- Three-table integration test: a blocked bot does not block other tables' reads, decisions,
  presentation windows or organizer pause commands. Its eventual failure records a local automatic
  action. Other players' private cards remain absent.
- Browser walkthroughs: landing, sign-in, invalid join code, human dashboard, join confirmation,
  lobby-to-table transition, real match all-in submission, showdown, final standings, Escape
  dismissal and final-hand review; organizer overview, embedded/standalone spectators and
  admin-only card/odds reveal; bot configuration validation, successful connection, all six
  decision checks using the repository's sample bot on the same machine's LAN address, and
  diagnostics empty state; password-help request and account-tool visibility; real-engine practice.
- Keyboard: R focuses the raise field; F while editing does not fold; shortcuts remain opt-in.
- Viewports: table at **1280×720** and **1440×900**; no document overflow at 1280×720 with details
  open or closed. Practice also fits 1280×720. A 390px phone and 640×360 zoom-equivalent CSS
  viewport allow scrolling with no horizontal overflow. Actual browser zoom was not changed.
- Long-content check: six 80-character names and maximum 10,000,000-chip starting stacks;
  names truncate at seats with full-name titles, chip amounts remain readable, final standings wrap.
- Reduced-motion code paths show authoritative cards immediately and disable the loader animation;
  the operating-system motion setting was not changed. Native keyboard/modal behavior was checked;
  a full screen-reader certification was not performed.
- Four disposable local matches, fourteen disposable accounts, dependent results/sessions/profile
  records and the temporary sample-bot process were removed after the walkthroughs. Existing
  accounts and matches were preserved. The local API was restarted after the interrupted turn.

### Local screenshots

Artifacts are intentionally untracked under `output/playwright/`:

- `table-before-1280.png`, `table-after-1280.png`
- `table-before-1440.png`, `table-after-1440.png`
- `dashboard-before-1440.png`, `dashboard-after-1280.png`
- `admin-before-1440.png`, `admin-after-1440.png`
- `showdown-after-1280.png`, `table-large-values.png`, `table-after-mobile.png`

Only table before/after pairs are directly comparable at matching dimensions. Earlier captures
of live walkthroughs record the state at capture time and may precede the final visual corrections.

## Remaining limitations and deferred checks

- Actual event-router rehearsal, multiple physical laptops, and the existing eight-hour bot soak
  remain operational acceptance work. A same-machine LAN sample-bot check does not establish them.
- No disposable PostgreSQL database was provisioned. The schema-reset suites were deliberately not
  pointed at the running development database.
- Phone polish remains secondary to laptop play. Actual browser zoom, a full screen-reader run,
  browser-level offline simulation, and measured slow-network playback were not completed.
  Snapshot ordering, pacing windows and failure isolation have focused regression coverage.
- The baseline FastAPI/Starlette test-client deprecation warning remains; dependency migration is
  outside this UI change.

## Adversarial acceptance

Amounts and clocks stay server authoritative. Local reveals never take time from a live human
choice. Reconnects show current state rather than replaying outdated action sequences. Repeated
submissions and older responses cannot overwrite a newer decision. Hidden opponent cards remain
private, including when the common renderer is used by practice, preview, and spectators. Larger
zoom-sized layouts scroll instead of shrinking controls. Physical chip stacks and meaningful
color remain part of the gameplay information design.
