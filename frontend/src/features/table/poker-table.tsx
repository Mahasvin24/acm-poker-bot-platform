"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { getSpectatorState, getTableState, submitTableAction, TableApiError } from "./api";
import styles from "./poker-table.module.css";
import { newerTable } from "./presentation";
import { PokerTableView } from "./poker-table-view";
import type { ActionSubmission, ActionType, PlayerTableState } from "./types";

type ConnectionState = "syncing" | "live" | "reconnecting";

interface PokerTableProps {
  matchId: string;
  mode?: "player" | "spectator";
  embedded?: boolean;
  exitHref?: string;
  revealCards?: boolean;
  fullScreen?: boolean;
}

interface AccessIssue {
  title: string;
  message: string;
  status?: number;
  retry: boolean;
}

function issueFromError(error: unknown): AccessIssue {
  if (error instanceof TableApiError) {
    if (error.status === 401) {
      return { status: 401, retry: false, title: "Sign in required", message: "Your seat is private. Sign in with the account that joined this match." };
    }
    if (error.status === 403) {
      return { status: 403, retry: false, title: "Not in this match", message: error.message };
    }
    if (error.status === 404) {
      return { status: 404, retry: false, title: "Match not found", message: error.message };
    }
    if (error.status === 409) {
      return { status: 409, retry: true, title: "Waiting for the table", message: error.message };
    }
    return { status: error.status, retry: true, title: "Reconnecting", message: error.message };
  }
  return { retry: true, title: "Connection interrupted", message: "The table could not be reached. Your chips and cards are safe on the server." };
}

function pollDelay(table: PlayerTableState): number {
  if (table.match_status === "completed" || table.match_status === "cancelled") return 5_000;
  if (table.decision || table.turn || table.next_action_at) return 400;
  return 1_000;
}

export function PokerTable({ matchId, mode = "player", embedded = false, exitHref = "/dashboard", revealCards = false, fullScreen = false }: PokerTableProps) {
  const [table, setTable] = useState<PlayerTableState | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("syncing");
  const [issue, setIssue] = useState<AccessIssue | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const interrupted = useRef(false);
  const submissionLock = useRef(false);
  const fetchState = useCallback((id: string, signal?: AbortSignal) =>
    mode === "spectator" ? getSpectatorState(id, signal, revealCards) : getTableState(id, signal), [mode, revealCards]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let failures = 0;
    const poll = async () => {
      controller = new AbortController();
      try {
        const next = await fetchState(matchId, controller.signal);
        if (stopped) return;
        failures = 0;
        setTable((current) => newerTable(current, next));
        if (interrupted.current) {
          setNotice("Connection restored.");
          interrupted.current = false;
        }
        setIssue(null);
        setConnection("live");
        timer = setTimeout(poll, pollDelay(next));
      } catch (error) {
        if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
        const nextIssue = issueFromError(error);
        failures += 1;
        interrupted.current = nextIssue.status !== 409;
        setIssue(nextIssue);
        setConnection(nextIssue.status === 409 ? "syncing" : "reconnecting");
        if (nextIssue.retry) timer = setTimeout(poll, Math.min(5_000, 800 * failures));
      }
    };
    const resume = () => {
      if (document.visibilityState === "hidden") return;
      setConnection("syncing");
      setRefreshToken((value) => value + 1);
    };
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    window.addEventListener("focus", resume);
    void poll();
    return () => {
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
      window.removeEventListener("focus", resume);
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [fetchState, matchId, refreshToken]);

  const submit = useCallback(async (action: ActionType, amountTo?: number) => {
    if (!table?.decision || submissionLock.current || connection !== "live") return;
    submissionLock.current = true;
    const submission: ActionSubmission = {
      decision_id: table.decision.decision_id,
      table_version: table.decision.table_version,
      action,
      ...(action === "raise" ? { amount_to: amountTo } : {}),
    };
    setSubmitting(true);
    setNotice(`Sending ${action}…`);
    try {
      const next = await submitTableAction(matchId, submission);
      setTable((current) => newerTable(current, next));
      setNotice(null);
    } catch (error) {
      if (error instanceof TableApiError && error.status === 409) {
        setNotice("The table moved on before that arrived. Showing the latest state.");
        try {
          const next = await getTableState(matchId);
          setTable((current) => newerTable(current, next));
        } catch (syncError) {
          setIssue(issueFromError(syncError));
          setConnection("reconnecting");
        }
      } else {
        setIssue(issueFromError(error));
        setConnection("reconnecting");
      }
    } finally {
      submissionLock.current = false;
      setSubmitting(false);
    }
  }, [matchId, connection, table]);

  if (!table) {
    return (
      <main className={embedded ? styles.gateEmbedded : styles.gate} id={embedded ? undefined : "main-content"}>
        <div className={styles.gateCard}>
          {!embedded && <Link className={styles.wordmark} href="/">ACM / POKER</Link>}
          {issue && !issue.retry ? (
            <>
              <p className={styles.kicker}>Match table</p><h1>{issue.title}</h1><p>{issue.message}</p>
              <div className={styles.gateActions}>
                {issue.status === 401
                  ? <Link href={`/account?next=${encodeURIComponent(`/match/${matchId}`)}`}>Sign In</Link>
                  : <button type="button" onClick={() => setRefreshToken((value) => value + 1)}>Try Again</button>}
                <Link href={exitHref}>Back to dashboard</Link>
              </div>
            </>
          ) : (
            <>
              <span className={styles.loader} aria-hidden="true" />
              <h1>{issue?.title ?? "Finding your table"}</h1>
              <p aria-live="polite">{issue?.message ?? "Loading the latest hand…"}</p>
            </>
          )}
        </div>
      </main>
    );
  }

  return (
    <PokerTableView
      connectionLabel={connection === "live" ? (mode === "spectator" ? "Spectating" : "Live") : connection}
      connectionTone={connection === "syncing" ? "reconnecting" : connection}
      embedded={embedded}
      fullScreen={fullScreen}
      error={issue && issue.status !== 409 ? issue.message : null}
      exitHref={exitHref}
      notice={notice}
      onSubmit={(action, amountTo) => void submit(action, amountTo)}
      submitting={submitting}
      table={table}
    />
  );
}
