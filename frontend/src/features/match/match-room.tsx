"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AccountApiError, getMatch, leaveMatch } from "../account/api";
import styles from "../account/account.module.css";
import { MATCH_STATUS_LABELS, type MatchView } from "../account/types";
import { useAccount } from "../account/use-account";
import { PokerTable } from "../table/poker-table";
import { formatConfig } from "./format";

export function MatchRoom({ matchId }: { matchId: string }) {
  const router = useRouter();
  const { account, error: accountError } = useAccount(`/match/${matchId}`);
  const [match, setMatch] = useState<MatchView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fatal, setFatal] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!account || (match && match.status !== "lobby")) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const next = await getMatch(matchId, controller.signal);
        if (stopped) return;
        setMatch(next);
        setError(null);
        if (next.status === "lobby") timer = setTimeout(poll, 1_500);
      } catch (reason) {
        if (stopped || (reason instanceof DOMException && reason.name === "AbortError")) return;
        if (reason instanceof AccountApiError && reason.status === 404) {
          setFatal(true);
          setError(reason.message);
          return;
        }
        setError(reason instanceof Error ? reason.message : "Reconnecting to the lobby…");
        timer = setTimeout(poll, 3_000);
      }
    };
    void poll();
    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [account, match, matchId]);

  if (match && match.status !== "lobby") {
    return <PokerTable matchId={matchId} />;
  }

  const leave = async (entryId: string) => {
    setBusy(true);
    try {
      await leaveMatch(matchId, entryId);
      const mine = match?.entries.filter((entry) => entry.mine && entry.entry_id !== entryId) ?? [];
      if (mine.length === 0) {
        router.push("/dashboard");
        return;
      }
      setMatch(await getMatch(matchId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not leave the match.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Match Lobby</span>
        <div className={styles.headerAccount}>
          {account && <span>{account.email}</span>}
          <Link className={styles.textButton} href="/dashboard">Dashboard</Link>
        </div>
      </header>
      <div className={styles.narrow}>
        {fatal || accountError ? (
          <section className={styles.panel}>
            <h2>This match isn’t available.</h2>
            <p className={styles.panelIntro}>{error ?? accountError}</p>
            <div className={styles.panelActions}>
              <Link className={styles.primaryButton} href="/join">Enter a code</Link>
            </div>
          </section>
        ) : !match ? (
          <div className={styles.loading}><span>Opening lobby</span></div>
        ) : (
          <section className={styles.panel} aria-live="polite">
            <div className={styles.panelHead}>
              <div>
                <p className={styles.sectionLabel}>{MATCH_STATUS_LABELS[match.status]}</p>
                <h2>{match.name}</h2>
                <p className={styles.panelIntro}>{formatConfig(match.config)}</p>
              </div>
              <span className={styles.statusPill} data-status="lobby">
                {match.entries.length}/{match.max_seats} seats
              </span>
            </div>
            <div className={styles.entrantBody}>
              <div className={styles.waiting}>
                <span className={styles.pulse} aria-hidden="true" />
                <p>Waiting for the organizer to start. The table opens here automatically.</p>
              </div>
              <ul className={styles.roster}>
                {match.entries.map((entry) => (
                  <li key={entry.entry_id}>
                    <span className={styles.kindTag} data-kind={entry.kind}>{entry.kind === "bot" ? "Bot" : "Human"}</span>
                    <strong>{entry.display_name}{entry.mine ? " (you)" : ""}</strong>
                    {entry.mine && entry.kind === "bot" && (
                      <small>{entry.bot_ready ? "Verified" : "Needs verification"}</small>
                    )}
                    {entry.mine && (
                      <button className={styles.textButton} disabled={busy} onClick={() => void leave(entry.entry_id)} type="button">
                        Leave
                      </button>
                    )}
                  </li>
                ))}
                {Array.from({ length: Math.max(0, match.max_seats - match.entries.length) }, (_, index) => (
                  <li className={styles.openSeat} key={`open-${index}`}><span>Open seat</span></li>
                ))}
              </ul>
              {error && <p className={styles.formError} role="alert">{error}</p>}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
