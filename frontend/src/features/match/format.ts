import type { MatchConfig } from "../account/types";

const chips = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatChips(value: number): string {
  return chips.format(value);
}

export function formatConfig(config: MatchConfig): string {
  const blinds = `${formatChips(config.small_blind)}/${formatChips(config.big_blind)} blinds`;
  const escalation = config.blind_increase_minutes
    ? `rising every ${config.blind_increase_minutes} min`
    : "fixed";
  const ante = config.big_blind_ante ? " + big-blind ante" : "";
  return `${config.max_seats} seats · ${formatChips(config.starting_stack)} chips · ${blinds}${ante} (${escalation}) · ${Math.round(config.human_action_timeout_ms / 1000)}s per decision`;
}

export function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

export function relativeTime(iso: string | null, now: number): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.floor(seconds / 60)}m ago`;
}
