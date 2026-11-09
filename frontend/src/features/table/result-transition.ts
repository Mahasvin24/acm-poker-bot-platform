import type { PlayerTableState, PlayerTournamentState } from "./types";

export function resultTransitionDelay(
  table: Pick<PlayerTableState, "completed"> | null, terminalUntil: number, now: number,
): number {
  if (!table) return 0; // Refresh: show durable results without waiting for an old hand.
  if (table.completed) return Math.max(0, terminalUntil - now);
  return 4000; // Give the table poll a bounded chance to retrieve the final hand.
}

export function acceptTournamentUpdate(
  current: PlayerTournamentState | null, next: PlayerTournamentState,
): PlayerTournamentState {
  if (current?.tournament_id === next.tournament_id) {
    if (current.status === "completed") return current;
    if (current.status === "eliminated" && next.status !== "completed") return current;
  }
  return next;
}
