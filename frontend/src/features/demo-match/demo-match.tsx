"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { newerTable } from "../table/presentation";
import { PokerTableView } from "../table/poker-table-view";
import type { ActionType } from "../table/types";
import {
  DemoApiError,
  endDemoMatch,
  getDemoMatch,
  startDemoMatch,
  submitDemoAction,
  type DemoMatchState,
} from "./api";
import styles from "./demo-match.module.css";

const idleMatch: DemoMatchState = {
  status: "idle",
  match_id: null,
  result: null,
  table: null,
};

export function DemoMatch() {
  const operationLock = useRef(false);
  const [match, setMatch] = useState<DemoMatchState>(idleMatch);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const update = useCallback((next: DemoMatchState, replaceMatch = false) => {
    setMatch((current) => {
      if (
        !replaceMatch &&
        current.match_id &&
        next.match_id &&
        current.match_id !== next.match_id
      ) {
        return current;
      }
      if (!replaceMatch && current.table && next.table && newerTable(current.table, next.table) === current.table) return current;
      return next;
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getDemoMatch(controller.signal)
      .then((next) => update(next, true))
      .catch((reason: unknown) => {
        if (!(reason instanceof DOMException && reason.name === "AbortError")) {
          setError(reason instanceof Error ? reason.message : "Could not load the demo match.");
        }
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [update]);

  useEffect(() => {
    if (match.status !== "active") return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await getDemoMatch();
        if (!stopped) {
          update(next);
          setError(null);
        }
      } catch (reason) {
        if (!stopped) {
          setError(reason instanceof Error ? reason.message : "The demo connection was interrupted.");
        }
      } finally {
        if (!stopped) timer = setTimeout(() => void poll(), 500);
      }
    };
    void poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [match.status, update]);

  const run = async (
    operation: () => Promise<DemoMatchState>,
    success: string,
    replaceMatch = false,
  ) => {
    if (operationLock.current) return;
    operationLock.current = true;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      update(await operation(), replaceMatch);
      setNotice(success);
    } catch (reason) {
      setError(reason instanceof DemoApiError ? reason.message : "The demo server could not be reached.");
    } finally {
      operationLock.current = false;
      setBusy(false);
    }
  };

  const act = (action: ActionType, amountTo?: number) => {
    const decision = match.table?.decision;
    if (!decision) return;
    void run(
      () => submitDemoAction({
        decision_id: decision.decision_id,
        table_version: decision.table_version,
        action,
        ...(amountTo === undefined ? {} : { amount_to: amountTo }),
      }),
      `You ${action}${amountTo === undefined ? "" : ` to ${amountTo}`}.`,
    );
    setNotice(`Submitting ${action}${amountTo === undefined ? "" : ` ${amountTo}`}…`);
  };

  if (!loading && match.status !== "idle" && match.table) {
    return (
      <main className={styles.livePage} id="main-content">
        <details className={styles.liveControls}>
          <summary>Practice controls</summary>
          <div>
            <button disabled={busy} onClick={() => void run(startDemoMatch, "Practice started.", true)}>Restart</button>
            <button disabled={busy} onClick={() => void run(endDemoMatch, "Practice ended.", true)}>Exit game</button>
          </div>
        </details>
        <PokerTableView
          connectionLabel="Four-player demo"
          connectionTone={error ? "reconnecting" : "demo"}
          embedded
          error={error}
          fullScreen
          key={match.match_id}
          notice={notice}
          onSubmit={act}
          showSidePots={false}
          submitting={busy}
          table={match.table}
        />
      </main>
    );
  }

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link href="/">ACM / POKER</Link>
        <span>Practice table</span>
        <Link href="/join">Join a real match</Link>
      </header>

      <section className={styles.intro}>
        <div><p>One human × three test bots</p><h1>Practice poker</h1></div>
        <p className={styles.explainer}>
          Play a hand against three bots. No account needed, and results do not affect your match history.
        </p>
      </section>

      {loading ? (
        <section className={styles.empty}><p>Connecting to the test table…</p></section>
      ) : match.status === "idle" ? (
        <section className={styles.empty}>
          {error && <p className={styles.error} role="alert">{error}</p>}
          <h2>Ready to play?</h2>
          <p>You’ll have 30 seconds for each decision.</p>
          <button disabled={busy} onClick={() => void run(startDemoMatch, "Practice started.", true)}>Deal the hand →</button>
        </section>
      ) : null}

      <footer className={styles.footer}>
        <span>Play money</span><span>Private to this browser</span>
      </footer>
    </main>
  );
}
