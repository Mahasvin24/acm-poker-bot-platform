export type ActionType = "fold" | "check" | "call" | "raise";
export type EntryKind = "human" | "bot";

export interface LegalAction {
  action: ActionType;
  amount: number | null;
  min_amount_to: number | null;
  max_amount_to: number | null;
}

export interface PlayerDecision {
  decision_id: string;
  table_version: number;
  deadline_at: string;
  duration_ms: number;
  legal_actions: LegalAction[];
}

export interface PublicTurn {
  seat: number;
  kind: EntryKind;
  deadline_at: string;
  duration_ms: number;
}

export interface HandAward {
  seat: number;
  amount: number;
  net: number;
}

export interface RevealedHand {
  seat: number;
  hole_cards: string[];
  label: string;
  best_five: string[];
}

export interface HandResult {
  reason: "showdown" | "fold";
  awards: HandAward[];
  winner_seats: number[];
  revealed_hands: RevealedHand[];
}

export interface PlayerSeat {
  seat: number;
  entrant_id: string;
  display_name: string;
  kind: EntryKind;
  stack: number;
  committed_this_street: number;
  committed_this_hand: number;
  folded: boolean;
  all_in: boolean;
  eliminated: boolean;
  away?: boolean;
  hole_cards: string[];
}

export interface PlayerAction {
  sequence: number;
  seat: number;
  street?: string | null;
  action: ActionType;
  amount_to: number | null;
  automatic: boolean;
  failure_reason: string | null;
}

export interface SidePot {
  amount: number;
  eligible_seats: number[];
}

export interface Standing {
  entry_id: string;
  display_name: string;
  kind: EntryKind;
  position: number;
  eliminated_hand_number: number | null;
  final_stack: number;
}

export interface Viewer {
  entry_id: string;
  display_name: string;
  status: "seated" | "eliminated" | "winner" | "finished";
  finish_position: number | null;
}

export interface MatchContext {
  name: string;
  level_number: number;
  level_remaining_seconds: number | null;
  next_small_blind: number | null;
  next_big_blind: number | null;
  players_remaining: number;
  max_seats: number;
  end_requested: boolean;
  standings: Standing[];
}

export interface LastHand {
  hand_number: number;
  community_cards: string[];
  result: HandResult;
  names: Record<string, string>;
}

export interface PlayerTableState {
  match_id: string;
  match_status: string;
  table_status: string;
  table_id: string;
  hand_id: string;
  hand_number: number;
  table_version: number;
  viewer_seat: number | null;
  viewer?: Viewer | null;
  acting_seat: number | null;
  street: string;
  button_seat: number;
  small_blind: number;
  big_blind: number;
  big_blind_ante: number;
  community_cards: string[];
  seats: PlayerSeat[];
  pot: number;
  side_pots: SidePot[];
  action_history: PlayerAction[];
  completed: boolean;
  decision: PlayerDecision | null;
  turn?: PublicTurn | null;
  hand_result?: HandResult | null;
  next_action_at?: string | null;
  match?: MatchContext | null;
  last_hand?: LastHand | null;
}

export interface ActionSubmission {
  decision_id: string;
  table_version: number;
  action: ActionType;
  amount_to?: number;
}
