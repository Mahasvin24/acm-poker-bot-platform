"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PokerTableView } from "../table/poker-table-view";
import type { ActionType } from "../table/types";
import {
  DemoApiError,
  endDemoMatch,
  forceDemoResult,
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
      }
    };
    const timer = window.setInterval(() => void poll(), 500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [match.status, update]);

  const run = async (
    operation: () => Promise<DemoMatchState>,
    success: string,
    replaceMatch = false,
  ) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      update(await operation(), replaceMatch);
      setNotice(success);
    } catch (reason) {
      setError(reason instanceof DemoApiError ? reason.message : "The demo server could not be reached.");
    } finally {
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
          <summary>Test controls</summary>
          <div>
            <button disabled={busy} onClick={() => void run(startDemoMatch, "A fresh match is live.", true)}>Restart</button>
            <button disabled={busy} onClick={() => void run(() => forceDemoResult("human_win"), "Forced a human win.")}>Force win</button>
            <button disabled={busy} onClick={() => void run(() => forceDemoResult("bot_win"), "Forced a human loss.")}>Force loss</button>
            <button disabled={busy} onClick={() => void run(endDemoMatch, "Match erased.", true)}>Exit game</button>
          </div>
        </details>
        <PokerTableView
          animateInitialDeal
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
        <span>EPHEMERAL TEST TABLE</span>
        <Link href="/play">Exit to Play</Link>
      </header>

      <section className={styles.intro}>
        <div><p>One human × three test bots</p><h1>One table.<br /><em>No trace.</em></h1></div>
        <p className={styles.explainer}>
          A real four-player hand powered by the production poker engine. This single in-memory
          match creates no account, tournament, entrant, event, or action records.
        </p>
      </section>

      <section aria-label="Demo match controls" className={styles.controlBar}>
        <button disabled={busy} onClick={() => void run(startDemoMatch, "A fresh match is live.", true)}>
          {match.status === "idle" ? "Start game" : "Restart game"}
        </button>
        <button disabled={busy || match.status === "idle"} onClick={() => void run(endDemoMatch, "Match erased.", true)}>End game</button>
        <span className={styles.controlDivider} />
        <span>Cheat states</span>
        <button disabled={busy || match.status === "idle"} onClick={() => void run(() => forceDemoResult("human_win"), "Forced a human win.")}>Force win</button>
        <button disabled={busy || match.status === "idle"} onClick={() => void run(() => forceDemoResult("bot_win"), "Forced a human loss.")}>Force loss</button>
      </section>

      {loading ? (
        <section className={styles.empty}><p>Connecting to the test table…</p></section>
      ) : match.status === "idle" ? (
        <section className={styles.empty}>
          {error && <p className={styles.error} role="alert">{error}</p>}
          <span>01 / READY</span><h2>The table is empty.</h2>
          <p>Start a game to take your seat against three deliberately paced test bots.</p>
          <button disabled={busy} onClick={() => void run(startDemoMatch, "A fresh match is live.", true)}>Deal the hand →</button>
        </section>
      ) : null}

      <footer className={styles.footer}>
        <span>IN-MEMORY ONLY</span><span>ONE CONCURRENT MATCH</span><span>30 SECOND HUMAN CLOCK</span><span>3 × 4 SECOND TEST BOTS</span>
      </footer>
    </main>
  );
}
