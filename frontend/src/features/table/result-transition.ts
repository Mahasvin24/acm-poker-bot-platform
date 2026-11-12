import type { PlayerTableState } from "./types";

export function resultTransitionDelay(
  table: Pick<PlayerTableState, "completed"> | null, terminalUntil: number, now: number,
): number {
  if (!table) return 0;
  if (table.completed) return Math.max(0, terminalUntil - now);
  return 4000;
}
