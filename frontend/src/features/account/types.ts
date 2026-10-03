export type AccountRole = "user" | "admin";
export type EntrantKind = "human" | "bot";

export interface Account {
  id: string;
  email: string;
  role: AccountRole;
  created_at: string;
}

export interface Entrant {
  id: string;
  tournament_id: string;
  kind: EntrantKind;
  display_name: string;
  bot_ip: string | null;
  bot_port: number | null;
  bot_verified_at: string | null;
}

export interface BotEndpointRegistration {
  entrant: Entrant;
  bearer_token: string;
}

export interface BlindLevel {
  small_blind: number;
  big_blind: number;
  big_blind_ante: number;
  duration_seconds: number;
}

export interface TournamentConfig {
  max_players: number;
  table_size: number;
  starting_stack: number;
  human_action_timeout_ms: number;
  bot_action_timeout_ms: number;
  bot_connect_timeout_ms: number;
  break_every_levels: number;
  break_duration_seconds: number;
  levels: BlindLevel[];
}

export interface AdminTournamentState {
  tournament_id: string;
  status: string;
  entrant_count: number;
  human_count: number;
  bot_count: number;
  verified_bot_count: number;
  table_count: number;
  level_number: number;
  phase_remaining_seconds: number;
  revision: number;
  config: TournamentConfig;
}

export interface AdminCommandResult {
  tournament_id: string;
  status: string;
}
