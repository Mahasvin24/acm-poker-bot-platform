import type { PlayerTableState } from "./types";

/** Never put a local reveal in front of a live decision or a reconnect snapshot. */
export function boardRevealSteps(previous: number, target: number, availableMs: number, hasDecision: boolean) {
  const counts = [3, 4, 5].filter((count) => count > previous && count <= target);
  if (hasDecision || availableMs < counts.length * 360 + 400) return [];
  return counts.map((count, index) => ({ count, delay: (index + 1) * 360 }));
}

/** Poll and action responses can cross; terminal match metadata may share a table version. */
export function newerTable(current: PlayerTableState | null, next: PlayerTableState): PlayerTableState {
  if (!current) return next;
  if (current.match_id !== next.match_id) return current;
  if (next.hand_number !== current.hand_number) return next.hand_number > current.hand_number ? next : current;
  if (next.table_version !== current.table_version) return next.table_version > current.table_version ? next : current;
  if (["completed", "cancelled"].includes(current.match_status) && !["completed", "cancelled"].includes(next.match_status)) return current;
  return next;
}

export function raisePresets(pot: number, call: number, committed: number, min: number, max: number) {
  const clamp = (amount: number) => Math.max(min, Math.min(max, Math.round(amount)));
  return [min, ...[0.5, 0.75, 1].map((fraction) => clamp(committed + call + (pot + call) * fraction)), max];
}

/** The big blind can check pre-flop, but increasing it is still a raise. */
export function isOpeningBet(street: string, canCheck: boolean): boolean {
  return canCheck && street !== "preflop";
}
