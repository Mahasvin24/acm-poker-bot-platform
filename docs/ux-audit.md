# Platform UX audit

## Brief and constraints

Experienced poker players, primarily on laptops. Keep ACM's identity, a shared table renderer,
one server-controlled pace, and independent matches (up to three concurrent tables).
No tournament brackets, balancing, API redesign, or new framework.

## Baseline — 2026-11-11

Clean working tree. Frontend: 9 tests pass. Integration/match suite: 72 pass, one
pre-existing failure in `test_hooks_bracket_play_and_reach_every_bot[True]` (no bot action
recorded before admin end). Investigate rather than masking it. Baseline table screenshots:
`output/playwright/table-before-1280.png` and `table-before-1440.png` (local artifacts).

| Severity | Screen / reproduction | Finding and impact | Resolution |
| --- | --- | --- | --- |
| High | `/play/demo`, 1280×720 | Header, stage tutorial, status row and 430px table push betting controls below the fold. | Planned: compact table frame and action dock. |
| High | Source: table presentation hook | New-hand animation depends on changing phase and completion values; an update can cancel its timers. Card counts are not atomically reset between hands. | Planned: stable hand-scoped presentation with regression coverage. |
| High | Source: player transport | Actions remain available on a stale snapshot after connection failure; conflict refresh bypasses monotonic state selection. | Planned: resync gate, submission lock, ordered snapshots. |
| Medium | Table seats | Stacks, cumulative contribution and street bets compete with tiny repeated labels; player cards overlap name panels. | Planned: readable cards, stack and street bet first. |
| Medium | Table status | Tutorial stages, header, dock and rail repeat the same information; clocks show distracting tenths continuously. | Planned: concise actor/street/clock and contextual details. |
| Medium | `/join` | “Seat one of your bots” contradicts one bot per account; headline repeats the task indirectly. | Planned: direct title and accurate account wording. |
| Medium | Landing | “Until one stack remains” omits timed/hand-limited endings; bot verification refers to obsolete “My Bots.” | Planned: correct copy and remove repeated promotional section. |
| Medium | Account/dashboard | Promotional headings and small tracked uppercase labels obscure functional tasks. | Planned: functional headings and readable shared controls. |
| Medium | Source: organizer overview | Creation form precedes match list; multiple active tables are difficult to scan quickly. | Planned: match overview first with code, occupancy and status. |
| Medium | Source: results overlay | Custom dialog lacks modal focus handling. | Planned: native dialog and focus restoration. |
| Low | Demo | Storage/engine implementation dominates the description. | Planned: practical explanation and one start action. |

## Verification still required

Authenticated player/bot/admin walkthroughs; actual mixed-table pacing; three-table isolation;
normal/admin spectator privacy; laptop screenshots after changes; zoom, keyboard, reduced motion,
long names and large chip amounts; lint/build and relevant backend checks.

## Adversarial acceptance

Removing text must preserve action amounts, deadlines, consequences and recovery. At enlarged
zoom, scroll instead of shrinking text. Never invent hidden cards, replay stale actions during
a live clock, or move gameplay timing into the browser. Keep failed/stale requests from submitting
against an obsolete decision. One slow table must not delay another table's reads or actions.
