"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { getPlayerTournamentState, getTableState, submitTableAction, TableApiError } from "./api";
import { createDemoTableState } from "./demo-state";
import styles from "./poker-table.module.css";
import { PokerTableView } from "./poker-table-view";
import { TournamentResults } from "./tournament-results";
import { acceptTournamentUpdate, resultTransitionDelay } from "./result-transition";
import type { ActionSubmission, ActionType, PlayerTableState, PlayerTournamentState } from "./types";

type ConnectionState = "syncing" | "live" | "reconnecting" | "demo";

interface PokerTableProps {
  tournamentId: string;
}

interface AccessIssue {
  title: string;
  message: string;
  status?: number;
  waiting?: boolean;
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
      if (error.code === "tournament_not_started") {
        return { status: error.status, waiting: true, title: "Waiting for tournament to start", message: "Your entry is registered. Your table will open automatically when the organizer starts play. Checking every 2 seconds…" };
      }
      return { status: error.status, title: "No active table available", message: "No active table is available for this entry. Check your dashboard or contact the organizer for your tournament status." };
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
  const [tournamentState, setTournamentState] = useState<PlayerTournamentState | null>(null);
  const [resultsReadyFor, setResultsReadyFor] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionState>(demoMode ? "demo" : "syncing");
  const [issue, setIssue] = useState<AccessIssue | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const terminalUntil = useRef(0);
  const connectionInterrupted = useRef(false);
  const results = tournamentState?.tournament_id === tournamentId &&
    (tournamentState.status === "eliminated" || tournamentState.status === "completed")
    ? tournamentState : null;
  const showingResults = results !== null && resultsReadyFor === tournamentId;
  const displayedHandId = table?.tournament_id === tournamentId ? table.hand_id : null;
  const displayedHandCompleted = table?.tournament_id === tournamentId && table.completed;
  const resultsStatus = results?.status;
  const stopTablePolling = showingResults || Boolean(results && displayedHandCompleted);

  useEffect(() => {
    if (!resultsStatus) return;
    const timer = setTimeout(
      () => setResultsReadyFor(tournamentId),
      resultTransitionDelay(displayedHandId ? { completed: Boolean(displayedHandCompleted) } : null, terminalUntil.current, Date.now()),
    );
    return () => clearTimeout(timer);
    // A repeated status poll must not restart the presentation clock.
  }, [resultsStatus, displayedHandId, displayedHandCompleted, tournamentId]);

  const mergeTable = useCallback((current: PlayerTableState | null, next: PlayerTableState) => {
    if (
      current?.completed &&
      next.hand_id !== current.hand_id &&
      Date.now() < terminalUntil.current
    ) {
      return current;
    }
    if (next.completed && (current?.hand_id !== next.hand_id || !current.completed)) {
      terminalUntil.current = Date.now() + 4_000;
    }
    if (!current || next.hand_id !== current.hand_id) return next;
    return next.table_version >= current.table_version ? next : current;
  }, []);

  useEffect(() => {
    if (demoMode) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const poll = async () => {
      controller = new AbortController();
      try {
        const next = await getPlayerTournamentState(tournamentId, controller.signal);
        if (stopped) return;
        setTournamentState((current) => acceptTournamentUpdate(current, next));
        if (next.status === "eliminated" || next.status === "completed") setIssue(null);
        if (next.status !== "completed") timer = setTimeout(poll, 2000);
      } catch (error) {
        if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
        const nextIssue = issueFromError(error);
        setIssue(nextIssue);
        if (!nextIssue.status || nextIssue.status >= 500) timer = setTimeout(poll, 1800);
      }
    };
    void poll();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [demoMode, refreshToken, tournamentId]);

  useEffect(() => {
    if (stopTablePolling) return;
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
        if (!nextIssue.waiting) connectionInterrupted.current = true;
        setIssue(nextIssue);
        setConnection("reconnecting");
        if (nextIssue.waiting) timer = setTimeout(poll, 2000);
        else if (!nextIssue.status || nextIssue.status >= 500) timer = setTimeout(poll, 1800);
      }
    };
    void poll();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [demoMode, mergeTable, refreshToken, stopTablePolling, tournamentId]);

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
      if (error instanceof TableApiError && error.status === 404 && !demoMode) {
        try {
          const next = await getPlayerTournamentState(tournamentId);
          if (next.status === "eliminated" || next.status === "completed") {
            setTournamentState((current) => acceptTournamentUpdate(current, next));
            setIssue(null);
          } else {
            setIssue(issueFromError(error));
          }
        } catch (statusError) {
          setIssue(issueFromError(statusError));
        }
      } else if (error instanceof TableApiError && error.status === 409) {
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

  if (results && showingResults) {
    return <TournamentResults result={results} error={issue?.status === 404 ? null : issue?.message ?? null} signInRequired={issue?.status === 401} onRetry={() => setRefreshToken((value) => value + 1)} />;
  }

  if (!table) {
    return (
      <main className={styles.gate} id="main-content">
        <div className={styles.gateCard}>
          <Link className={styles.wordmark} href="/">ACM / POKER</Link>
          {issue ? (
            <>
              {issue.waiting && <span className={styles.loader} aria-hidden="true" />}
              <p className={styles.kicker}>Player table</p><h1 aria-live="polite">{issue.title}</h1><p>{issue.message}</p>
              <div className={styles.gateActions}>
                {issue.status === 401 ? <Link href={`/account?tournament=${encodeURIComponent(tournamentId)}`}>Sign In</Link> : !issue.waiting && <button type="button" onClick={() => setRefreshToken((value) => value + 1)}>Try Again</button>}
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
