"use client";

import { useEffect, useRef, useState } from "react";

import { testBot } from "./api";
import styles from "./account.module.css";
import type { BotTestReport } from "./types";

export function BotTestPanel({ tournamentId, configured }: { tournamentId: string; configured: boolean }) {
  const [report, setReport] = useState<BotTestReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  const run = async () => {
    if (controller.current) return;
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      const next = await testBot(tournamentId, request.signal);
      if (!request.signal.aborted) setReport(next);
    } catch (reason) {
      if (!request.signal.aborted) setError(reason instanceof Error ? reason.message : "Bot testing failed. Try again.");
    } finally {
      if (!request.signal.aborted) setBusy(false);
      controller.current = null;
    }
  };

  return (
    <section className={styles.protocolSection} aria-labelledby="bot-testing-heading" aria-busy={busy}>
      <h3 id="bot-testing-heading">Test My Bot</h3>
      <p className={styles.panelIntro}>
        Run six protocol checks while registration is open. Allow up to 20 seconds.
        Tests use synthetic decisions and do not mark your bot verified or enter it into a game.
        Any advertised legal action passes; choosing a raise is optional.
      </p>
      <button className={styles.secondaryButton} disabled={!configured || busy} onClick={() => void run()} type="button">
        {busy ? "Testing Bot…" : "Test My Bot"}
      </button>
      {busy && <p role="status">Checking health, authentication, and four poker decisions…</p>}
      {error && <p className={styles.formError} role="alert">{error}</p>}
      {report && (
        <div aria-live="polite">
          <p className={report.passed ? styles.successMessage : styles.formError}>
            {report.passed ? "All checks passed." : "Some checks failed. Review the report and your bot logs."}
          </p>
          <ul className={styles.botTestReport}>
            {report.checks.map((check) => (
              <li key={check.name}>
                <strong>{check.passed ? "PASS" : "FAIL"} · {check.name} · {check.elapsed_ms} ms</strong>
                <p>{check.description}</p>
                <p>{check.message}{check.action && ` Returned ${check.action}${check.amount_to === null ? "" : ` to ${check.amount_to}`}.`}</p>
              </li>
            ))}
          </ul>
          <p className={styles.panelIntro}>Passing checks confirms protocol compatibility for these scenarios, not strategy strength or event network readiness.</p>
        </div>
      )}
    </section>
  );
}
