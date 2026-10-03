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
  legal_actions: LegalAction[];
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
  hole_cards: string[];
}

export interface PlayerAction {
  sequence: number;
  seat: number;
  action: ActionType;
  amount_to: number | null;
  automatic: boolean;
  failure_reason: string | null;
}

export interface SidePot {
  amount: number;
  eligible_seats: number[];
}

export interface PlayerTableState {
  tournament_id: string;
  tournament_status: string;
  table_status: string;
  table_id: string;
  hand_id: string;
  hand_number: number;
  table_version: number;
  viewer_seat: number;
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
}

export interface ActionSubmission {
  decision_id: string;
  table_version: number;
  action: ActionType;
  amount_to?: number;
}
