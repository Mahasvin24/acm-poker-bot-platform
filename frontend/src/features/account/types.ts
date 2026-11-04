export type Role = "user" | "admin";
export type EntrantKind = "human" | "bot";
export type MatchStatus =
  | "lobby"
  | "running"
  | "pause_requested"
  | "paused"
  | "completed"
  | "cancelled";

export interface Account {
  id: string;
  email: string;
  role: Role;
  created_at: string;
}

export interface PasswordReset {
  account: Account;
  temporary_password: string;
}

export interface BotProfile {
  id: string;
  name: string;
  ip: string;
  port: number;
  verified_at: string | null;
  last_verification_error: string | null;
  created_at: string;
}

export interface BotToken {
  bot: BotProfile;
  bearer_token: string;
}

export interface BotDecisionLog {
  match_id: string;
  hand_id: string;
  at: string;
  latency_ms: number;
  action: string;
  amount_to: number | null;
  failure_reason: string | null;
  explanation: string | null;
}

export interface BotDiagnostics {
  bot: BotProfile;
  decisions: number;
  failures: Record<string, number>;
  consecutive_failures: number;
  recent: BotDecisionLog[];
}

export interface MatchConfig {
  max_seats: number;
  starting_stack: number;
  small_blind: number;
  big_blind: number;
  big_blind_ante: boolean;
  human_action_timeout_ms: number;
  blind_increase_minutes: number | null;
}

export interface MatchPreview {
  match_id: string;
  name: string;
  status: MatchStatus;
  seats_taken: number;
  max_seats: number;
  config: MatchConfig;
  joinable: boolean;
  reason: string | null;
}

export interface Standing {
  entry_id: string;
  display_name: string;
  kind: EntrantKind;
  position: number;
  eliminated_hand_number: number | null;
  final_stack: number;
}

export interface LobbyEntry {
  entry_id: string;
  display_name: string;
  kind: EntrantKind;
  mine: boolean;
  bot_ready: boolean | null;
}

export interface MatchView {
  match_id: string;
  name: string;
  status: MatchStatus;
  max_seats: number;
  config: MatchConfig;
  entries: LobbyEntry[];
  standings: Standing[];
  level_number: number;
  level_remaining_seconds: number | null;
  end_requested: boolean;
  created_at: string;
}

export interface MyMatch {
  match_id: string;
  name: string;
  status: MatchStatus;
  seats_taken: number;
  max_seats: number;
  my_entries: LobbyEntry[];
  created_at: string;
}

export interface AdminEntry {
  entry_id: string;
  display_name: string;
  kind: EntrantKind;
  account_email: string | null;
  bot_name: string | null;
  bot_ready: boolean | null;
  bot_endpoint: string | null;
  state: "lobby" | "seated" | "eliminated" | "finished";
  seat: number | null;
  stack: number | null;
  away: boolean;
  last_seen_at: string | null;
  bot_decisions: number;
  bot_failures: number;
  bot_consecutive_failures: number;
}

export interface AdminMatchSummary {
  match_id: string;
  name: string;
  status: MatchStatus;
  join_code: string | null;
  seats_taken: number;
  max_seats: number;
  players_remaining: number;
  created_at: string;
}

export interface AdminMatch {
  match_id: string;
  name: string;
  status: MatchStatus;
  join_code: string | null;
  config: MatchConfig;
  entries: AdminEntry[];
  standings: Standing[];
  hand_number: number;
  level_number: number;
  level_remaining_seconds: number | null;
  end_requested: boolean;
  table_quarantined: boolean;
  created_at: string;
  revision: number;
}

export const DEFAULT_MATCH_CONFIG: MatchConfig = {
  max_seats: 6,
  starting_stack: 20_000,
  small_blind: 100,
  big_blind: 200,
  big_blind_ante: false,
  human_action_timeout_ms: 30_000,
  blind_increase_minutes: null,
};

export const MATCH_STATUS_LABELS: Record<MatchStatus, string> = {
  lobby: "Lobby open",
  running: "In play",
  pause_requested: "Pausing after this hand",
  paused: "Paused",
  completed: "Finished",
  cancelled: "Cancelled",
};
