from __future__ import annotations

from poker_bot_platform.auth.models import MatchResultSummary
from poker_bot_platform.domain import EntryKind, MatchStatus
from poker_bot_platform.match.models import MatchState


def match_result_rows(state: MatchState) -> tuple[MatchResultSummary, ...]:
    if state.status is not MatchStatus.COMPLETED or not state.standings:
        return ()
    entry_accounts = {entry.entry_id: entry.account_id for entry in state.entries}
    starting = state.config.starting_stack
    rows: list[MatchResultSummary] = []
    for standing in state.standings:
        account_id = entry_accounts.get(standing.entry_id)
        if account_id is None:
            continue
        rows.append(
            MatchResultSummary(
                account_id=account_id,
                entry_id=standing.entry_id,
                match_id=state.match_id,
                match_name=state.name,
                position=standing.position,
                final_stack=standing.final_stack,
                chip_delta=standing.final_stack - starting,
                display_name=standing.display_name,
                kind=standing.kind if isinstance(standing.kind, EntryKind) else EntryKind(standing.kind),
            )
        )
    return tuple(rows)
