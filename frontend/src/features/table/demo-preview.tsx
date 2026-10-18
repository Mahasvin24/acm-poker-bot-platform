"use client";

import { useEffect, useState } from "react";

import { createDemoTableState } from "./demo-state";
import { PokerTableView } from "./poker-table-view";
import type { ActionType, PlayerTableState } from "./types";

function applyPreviewAction(state: PlayerTableState, action: ActionType, amountTo?: number): PlayerTableState {
  const viewer = state.seats.find((seat) => seat.seat === state.viewer_seat);
  if (!viewer) return state;
  const legal = state.decision?.legal_actions.find((item) => item.action === action);
  const delta = action === "call"
    ? legal?.amount ?? 0
    : action === "raise"
      ? Math.max(0, (amountTo ?? 0) - viewer.committed_this_street)
      : 0;
  return {
    ...state,
    table_version: state.table_version + 1,
    acting_seat: 1,
    pot: state.pot + delta,
    decision: null,
    turn: null,
    seats: state.seats.map((seat) => seat.seat === state.viewer_seat ? {
      ...seat,
      stack: Math.max(0, seat.stack - delta),
      committed_this_street: seat.committed_this_street + delta,
      committed_this_hand: seat.committed_this_hand + delta,
      folded: action === "fold",
    } : seat),
    action_history: [...state.action_history, {
      sequence: state.action_history.length + 8,
      seat: viewer.seat,
      street: state.street,
      action,
      amount_to: amountTo ?? null,
      automatic: false,
      failure_reason: null,
    }],
  };
}

export function DemoPreviewTable() {
  const [table, setTable] = useState<PlayerTableState | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setTable(createDemoTableState()), 0);
    return () => window.clearTimeout(timer);
  }, []);

  if (!table) return null;
  return (
    <PokerTableView
      connectionLabel="Interface preview"
      connectionTone="demo"
      error={null}
      exitHref="/"
      notice={notice}
      onSubmit={(action, amountTo) => {
        setTable((current) => (current ? applyPreviewAction(current, action, amountTo) : current));
        setNotice("Preview only: nothing was sent to a server.");
      }}
      submitting={false}
      table={table}
    />
  );
}
