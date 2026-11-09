"use client";

import { useEffect, useState } from "react";

import { relativeTime } from "../match/format";
import { getBotDiagnostics } from "./api";
import styles from "./account.module.css";
import type { BotDiagnostics } from "./types";
import { useAccount } from "./use-account";

export function BotDiagnosticsWindow({ botId }: { botId: string }) {
  const { account, error: accountError } = useAccount(`/dashboard/bots/${encodeURIComponent(botId)}/diagnostics`);
  const [snapshot, setSnapshot] = useState<{ data: BotDiagnostics; loadedAt: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!account) return;
    let active = true;
    const load = async () => {
      try {
        const data = await getBotDiagnostics(botId);
        if (active) {
          setSnapshot({ data, loadedAt: Date.now() });
          setError(null);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load diagnostics.");
      }
    };
    void load();
    const interval = window.setInterval(() => void load(), 5_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [account, botId]);

  return (
    <main className={`${styles.page} ${styles.diagnosticsWindow}`} id="main-content">
      <header className={styles.diagnosticsWindowHeader}>
        <div>
          <p className={styles.sectionLabel}>ACM / Poker</p>
          <h1>{snapshot ? `${snapshot.data.bot.name} diagnostics` : "Bot diagnostics"}</h1>
        </div>
        <button className={styles.textButton} onClick={() => window.close()} type="button">Close</button>
      </header>
      <p className={styles.fieldHint}>Updates every 5 seconds. Keep this window open while your bot plays.</p>
      {(accountError || error) && <p className={styles.formError} role="alert">{accountError || error}</p>}
      {!snapshot ? <p role="status">{error || accountError ? "Waiting to reconnect…" : "Loading diagnostics…"}</p> : (
        <section className={styles.diagnostics} aria-label="Bot activity">
          <p>
            {snapshot.data.decisions} decisions this session ·{" "}
            {Object.values(snapshot.data.failures).reduce((total, count) => total + count, 0)} automatic fallbacks
            {snapshot.data.consecutive_failures >= 3 ? " · health-check mode (bot looks unreachable)" : ""}
          </p>
          {snapshot.data.recent.length === 0 ? (
            <p>No decisions yet. They’ll appear here when your bot plays a hand.</p>
          ) : (
            <ol>
              {snapshot.data.recent.slice(0, 12).map((item) => (
                <li data-failed={item.failure_reason ? "true" : undefined} key={`${item.hand_id}-${item.at}`}>
                  <span>{relativeTime(item.at, snapshot.loadedAt)}</span>
                  <strong>{item.failure_reason ? `${item.action} (automatic)` : `${item.action}${item.amount_to ? ` to ${item.amount_to}` : ""}`}</strong>
                  <small>{item.latency_ms} ms</small>
                  {item.explanation && <p>{item.explanation}</p>}
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
    </main>
  );
}
