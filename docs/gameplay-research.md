# Poker Gameplay Research

This note records the product decisions drawn from established tournament structures and online
poker clients. It is intentionally limited to features that improve comprehension, fairness, or
decision speed for an amateur club tournament.

## Tournament structure

The default remains a 20,000-chip starting stack with opening blinds of 100/200 and a 200
big-blind ante. That is a 100-big-blind starting stack. A published 2024 WSOP Circuit event uses
the same stack, opening blinds, and big-blind ante, then progresses through 200/300, 200/400,
300/500, and similarly smooth steps. The platform now follows that 29-level progression through
75,000/150,000 rather than skipping intermediate levels.

The small blind is usually one half of the big blind, but a balanced schedule need not maintain
that ratio at every level. Steps such as 200/300, 1,000/1,500, and 1,500/2,500 are intentional:
they limit the increase in the big blind to 50% or less while preserving practical chip units.

Fifteen-minute levels are retained. PokerStars classifies 15-minute levels as its “Slow” online
speed, which is appropriate for an event mixing humans and bots. Breaks now occur for five
minutes after every fourth level: one break per hour, consistent with the hourly cadence used by
online tournaments, without the previous ten-minute interruption every 45 minutes.

Sources:

- [2024 WSOP Circuit Event #14 structure](https://www.wsop.com/pdfs/structuresheets/structure_5579_23915.pdf)
- [PokerStars tournament speeds](https://www.pokerstars.com/help/articles/tournament-speed/)
- [PokerStars tournament break rules](https://www.pokerstars.com/poker/tournaments/rules/)

## Table interaction

Implemented now:

- Exact raises use a number field with validation and Enter-to-submit. The imprecise range slider
  is removed.
- Quick sizing buttons provide Min Raise, 1/2 Pot, 3/4 Pot, Pot, and All In. PokerStars exposes
  configurable bet-size shortcuts for the same reason: common decisions should not require
  typing.
- The human stack is shown in dollars and big blinds. Dollar values remain concrete for novice
  players while big-blind depth makes tournament decisions comparable as blinds rise.
- Action narration, paced dealing, a public turn clock, a collapsible hand history, and visible
  player states remain the primary comprehension layer.

Sources:

- [PokerStars bet shortcuts](https://www.pokerstars.com/help/articles/bet-slider-options/)
- [PokerStars table display and announcements](https://www.pokerstars.com/help/articles/table-appearance-feature/232136/)

## Recommended next features

1. **Tournament context in the table sidebar.** Show the current level, time remaining, next
   blinds, the next break, and the human stack in big blinds. Established clients put structure
   information in the tournament lobby; surfacing the next change at the table avoids context
   switching.
2. **A bounded human time bank.** PokerStars uses a short regular decision clock plus a reserve
   time bank. The current 30-second clock is intentionally generous for novices, so a time bank
   should be added only if normal decisions are later shortened. It must be server-authoritative
   and allocated equally.
3. **Previous-hand replay.** A visual replay would let players understand a fast or surprising
   hand without slowing the live table. PokerStars exposes the previous-hand replayer directly
   from the table.
4. **Optional hand-strength explanation.** PokerStars offers a novice-oriented current hand
   strength label above the betting controls. If added here, it must be derived by the server's
   poker engine and explain the made hand without giving strategic advice.
5. **Optional keyboard shortcuts and pre-actions.** These help experienced users, but should be
   opt-in and visibly armed to prevent accidental folds or raises.

Sources:

- [PokerStars decision time and time bank](https://www.pokerstars.com/help/articles/trn-time-bank/)
- [PokerStars previous-hand replay](https://www.pokerstars.com/help/articles/replay-feature/36332/)
- [PokerStars hand-strength feature](https://www.pokerstars.com/help/articles/hand-strength-rm-pm/94663/)
- [PokerStars desktop table features](https://www.pokerstars.com/poker/room/features/software-news/)
