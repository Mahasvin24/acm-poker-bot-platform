"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { getTableState, submitTableAction, TableApiError } from "./api";
import { createDemoTableState } from "./demo-state";
import styles from "./poker-table.module.css";
import { PokerTableView } from "./poker-table-view";
import type { ActionSubmission, ActionType, PlayerTableState } from "./types";

type ConnectionState = "syncing" | "live" | "reconnecting" | "demo";

interface PokerTableProps {
  tournamentId: string;
}

interface AccessIssue {
  title: string;
  message: string;
  status?: number;
}

function actionCopy(action: ActionType): string {
  return action.charAt(0).toUpperCase() + action.slice(1);
}

function issueFromError(error: unknown): AccessIssue {
  if (error instanceof TableApiError) {
    if (error.status === 401) {
      return { status: error.status, title: "Sign in required", message: "Your table is private. Sign in with your tournament account, then try again." };
    }
    if (error.status === 403) {
      return { status: error.status, title: "No player entry found", message: "This account is not registered as a human entrant in this tournament." };
    }
    if (error.status === 404) {
      return { status: error.status, title: "Waiting for a seat", message: "The tournament has not assigned this entrant to an active table yet." };
    }
    return { status: error.status, title: "Table unavailable", message: error.message };
  }
  return { title: "Connection interrupted", message: "The table could not be reached. Your chips and cards remain safe on the server." };
}

function applyPreviewAction(state: PlayerTableState, submission: ActionSubmission): PlayerTableState {
  const viewer = state.seats.find((seat) => seat.seat === state.viewer_seat);
  if (!viewer) return state;
  const legal = state.decision?.legal_actions.find((item) => item.action === submission.action);
  const delta = submission.action === "call"
    ? legal?.amount ?? 0
    : submission.action === "raise"
      ? Math.max(0, (submission.amount_to ?? 0) - viewer.committed_this_street)
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
      folded: submission.action === "fold",
    } : seat),
    action_history: [...state.action_history, {
      sequence: state.action_history.length + 8,
      seat: state.viewer_seat,
      action: submission.action,
      amount_to: submission.amount_to ?? null,
      automatic: false,
      failure_reason: null,
    }],
  };
}

export function PokerTable({ tournamentId }: PokerTableProps) {
  const demoMode = tournamentId === "demo";
  const [table, setTable] = useState<PlayerTableState | null>(null);
  const [connection, setConnection] = useState<ConnectionState>(demoMode ? "demo" : "syncing");
  const [issue, setIssue] = useState<AccessIssue | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const terminalUntil = useRef(0);
  const connectionInterrupted = useRef(false);

  const mergeTable = useCallback((current: PlayerTableState | null, next: PlayerTableState) => {
    if (next.completed) terminalUntil.current = Date.now() + 4_000;
    if (
      current?.completed &&
      next.hand_id !== current.hand_id &&
      Date.now() < terminalUntil.current
    ) {
      return current;
    }
    if (!current || next.hand_id !== current.hand_id) return next;
    return next.table_version >= current.table_version ? next : current;
  }, []);

  useEffect(() => {
    if (demoMode) {
      const timer = window.setTimeout(() => setTable(createDemoTableState()), 0);
      return () => window.clearTimeout(timer);
    }

    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const poll = async () => {
      controller = new AbortController();
      try {
        const next = await getTableState(tournamentId, controller.signal);
        if (stopped) return;
        setTable((current) => mergeTable(current, next));
        if (connectionInterrupted.current) {
          setNotice("Connection restored.");
          connectionInterrupted.current = false;
        }
        setIssue(null);
        setConnection("live");
        timer = setTimeout(poll, next.turn || next.decision ? 500 : 1200);
      } catch (error) {
        if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
        const nextIssue = issueFromError(error);
        connectionInterrupted.current = true;
        setIssue(nextIssue);
        setConnection("reconnecting");
        if (!nextIssue.status || nextIssue.status >= 500) timer = setTimeout(poll, 1800);
      }
    };
    void poll();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [demoMode, mergeTable, refreshToken, tournamentId]);

  const submit = async (action: ActionType, amountTo?: number) => {
    if (!table?.decision || submitting) return;
    const submission: ActionSubmission = {
      decision_id: table.decision.decision_id,
      table_version: table.decision.table_version,
      action,
      ...(action === "raise" ? { amount_to: amountTo } : {}),
    };
    setSubmitting(true);
    setNotice(`Submitting ${action}${amountTo === undefined ? "" : ` ${amountTo}`}…`);
    try {
      if (demoMode) {
        setTable((current) => current ? applyPreviewAction(current, submission) : current);
      } else {
        const next = await submitTableAction(tournamentId, submission);
        setTable((current) => mergeTable(current, next));
      }
      setNotice(`You ${actionCopy(action).toLowerCase()}${amountTo === undefined ? "" : ` to ${amountTo}`}.`);
    } catch (error) {
      if (error instanceof TableApiError && error.status === 409) {
        setNotice("The table advanced before that action arrived. Resyncing now.");
        try {
          setTable(await getTableState(tournamentId));
        } catch (syncError) {
          setIssue(issueFromError(syncError));
        }
      } else {
        setIssue(issueFromError(error));
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (!table) {
    return (
      <main className={styles.gate} id="main-content">
        <div className={styles.gateCard}>
          <Link className={styles.wordmark} href="/">ACM / POKER</Link>
          {issue ? (
            <>
              <p className={styles.kicker}>Player table</p><h1>{issue.title}</h1><p>{issue.message}</p>
              <div className={styles.gateActions}>
                {issue.status === 401 ? <Link href={`/account?tournament=${encodeURIComponent(tournamentId)}`}>Sign In</Link> : <button type="button" onClick={() => setRefreshToken((value) => value + 1)}>Try Again</button>}
                <Link href="/play">Change tournament</Link>
              </div>
            </>
          ) : (
            <><span className={styles.loader} aria-hidden="true" /><h1>Finding your table</h1><p aria-live="polite">Syncing the latest committed hand and seat assignment…</p></>
          )}
        </div>
      </main>
    );
  }

  return (
    <PokerTableView
      connectionLabel={connection === "demo" ? "Demo table" : connection}
      connectionTone={connection === "syncing" ? "reconnecting" : connection}
      error={issue?.message ?? null}
      notice={notice}
      onSubmit={(action, amountTo) => void submit(action, amountTo)}
      submitting={submitting}
      table={table}
    />
  );
}
