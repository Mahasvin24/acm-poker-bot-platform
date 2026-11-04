"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  getAdminMatch,
  kickEntry,
  regenerateCode,
  revokeCode,
  runMatchCommand,
  startMatch,
  type AdminCommand,
} from "../account/api";
import styles from "../account/account.module.css";
import { MATCH_STATUS_LABELS, type AdminEntry, type AdminMatch } from "../account/types";
import { useAccount } from "../account/use-account";
import { PokerTable } from "../table/poker-table";
import { formatChips, formatConfig, formatDuration, relativeTime } from "./format";

function entryHealth(entry: AdminEntry, now: number): { tone: "ok" | "warn" | "muted"; text: string } {
  if (entry.state === "eliminated" || entry.state === "finished") return { tone: "muted", text: entry.state === "finished" ? "Finished" : "Out" };
  if (entry.kind === "bot") {
    if (!entry.bot_ready) return { tone: "warn", text: "Not verified" };
    if (entry.bot_consecutive_failures >= 3) return { tone: "warn", text: "Unresponsive" };
    if (entry.bot_failures > 0) return { tone: "ok", text: `${entry.bot_failures} fallbacks` };
    return { tone: "ok", text: entry.state === "lobby" ? "Verified" : "Healthy" };
  }
  if (entry.away) return { tone: "warn", text: "Away" };
  if (entry.state === "lobby") return { tone: "ok", text: "Joined" };
  const seen = entry.last_seen_at ? (now - Date.parse(entry.last_seen_at)) / 1000 : Infinity;
  return seen > 15
    ? { tone: "warn", text: `Last seen ${relativeTime(entry.last_seen_at, now)}` }
    : { tone: "ok", text: "Connected" };
}

export function AdminMatchConsole({ matchId }: { matchId: string }) {
  const { account, error: accountError } = useAccount(`/admin/match/${matchId}`);
  const [match, setMatch] = useState<AdminMatch | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [canForce, setCanForce] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const refresh = useCallback(async () => {
    setMatch(await getAdminMatch(matchId));
    setNow(Date.now());
  }, [matchId]);

  useEffect(() => {
    if (!account) return;
    const timer = window.setTimeout(() => void refresh().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load the match.")), 0);
    const interval = window.setInterval(() => void refresh().catch(() => undefined), 2_000);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(interval);
    };
  }, [account, refresh]);

  const run = async (label: string, operation: () => Promise<AdminMatch>, success: string) => {
    setBusy(label);
    setError(null);
    setNotice(null);
    try {
      setMatch(await operation());
      setNotice(success);
      setCanForce(false);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "That command failed.";
      setError(message);
      setCanForce(label === "start" && message.includes("not ready"));
    } finally {
      setBusy(null);
    }
  };

  const command = (name: AdminCommand, success: string, confirm?: string) => {
    if (confirm && !window.confirm(confirm)) return;
    void run(name, () => runMatchCommand(matchId, name), success);
  };

  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setNotice(`${label} copied.`);
    } catch {
      setError("Copy failed; select the text instead.");
    }
  };

  if (!account || !match) {
    return (
      <main className={styles.page} id="main-content">
        <div className={styles.loading}><span>{accountError ?? error ?? "Loading match"}</span></div>
      </main>
    );
  }

  const joinUrl = match.join_code && typeof window !== "undefined"
    ? `${window.location.origin}/join/${match.join_code.replace("-", "")}`
    : null;
  const playing = ["running", "pause_requested", "paused"].includes(match.status);
  const over = match.status === "completed" || match.status === "cancelled";

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/admin">← ALL MATCHES</Link>
        <span className={styles.headerTitle}>{match.name}</span>
        <div className={styles.headerAccount}><span>{account.email}</span></div>
      </header>

      <div className={styles.dashboard}>
        <section className={styles.consoleHead}>
          <div>
            <p className={styles.sectionLabel}>{MATCH_STATUS_LABELS[match.status]}{match.end_requested ? " · ending after this hand" : ""}</p>
            <h1 className={styles.consoleTitle}>{match.name}</h1>
            <p className={styles.panelIntro}>{formatConfig(match.config)}</p>
          </div>
          <div className={styles.codeCard}>
            <span>Join code</span>
            <strong translate="no">{match.join_code ?? "—"}</strong>
            {match.join_code && joinUrl ? (
              <div className={styles.panelActions}>
                <button className={styles.copyButton} onClick={() => void copy(match.join_code ?? "", "Code")} type="button">Copy code</button>
                <button className={styles.copyButton} onClick={() => void copy(joinUrl, "Join link")} type="button">Copy link</button>
              </div>
            ) : (
              <p className={styles.fieldHint}>{over ? "Codes are released when a match ends." : "No active code. Generate one to let players join."}</p>
            )}
            {!over && (
              <div className={styles.panelActions}>
                <button className={styles.textButton} disabled={busy !== null} onClick={() => void run("code", () => regenerateCode(matchId), "New code generated; the old one stopped working.")} type="button">New code</button>
                {match.join_code && (
                  <button className={styles.textButton} disabled={busy !== null} onClick={() => void run("revoke", () => revokeCode(matchId), "Code revoked.")} type="button">Revoke</button>
                )}
              </div>
            )}
          </div>
        </section>

        <section className={styles.commandBar} aria-label="Match controls">
          {match.status === "lobby" && (
            <>
              <button
                className={styles.dangerButton}
                disabled={busy !== null || match.entries.length < 2}
                onClick={() => void run("start", () => startMatch(matchId), "Match started. Cards are being dealt.")}
                type="button"
              >
                {busy === "start" ? "Checking bots…" : `Start match (${match.entries.length} players)`}
              </button>
              {canForce && (
                <button className={styles.secondaryButton} disabled={busy !== null} onClick={() => void run("force", () => startMatch(matchId, true), "Match started without the unresponsive bots answering.")} type="button">
                  Start anyway
                </button>
              )}
              {match.entries.length < 2 && <span className={styles.fieldHint}>At least two players must join.</span>}
            </>
          )}
          {match.status === "running" && (
            <button className={styles.secondaryButton} disabled={busy !== null} onClick={() => command("pause", "Pausing after the current hand.")} type="button">Pause after hand</button>
          )}
          {(match.status === "paused" || match.status === "pause_requested") && (
            <button className={styles.primaryButton} disabled={busy !== null} onClick={() => command("resume", "Match resumed.")} type="button">Resume</button>
          )}
          {playing && !match.end_requested && (
            <button className={styles.secondaryButton} disabled={busy !== null} onClick={() => command("end", "The match will end after this hand.", "End the match after the current hand? Remaining players are ranked by chips.")} type="button">End match</button>
          )}
          {!over && (
            <button className={styles.textButton} disabled={busy !== null} onClick={() => command("cancel", "Match cancelled.", "Cancel this match now? The current hand is abandoned and no standings are kept.")} type="button">Cancel match</button>
          )}
          {match.table_quarantined && <span className={styles.formError}>The table stopped after an engine error. End the match to record standings.</span>}
          {notice && <span className={styles.successMessage} role="status">{notice}</span>}
          {error && <span className={styles.formError} role="alert">{error}</span>}
        </section>

        <div className={styles.consoleGrid}>
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <div>
                <p className={styles.sectionLabel}>Roster</p>
                <h2>{match.entries.length}/{match.config.max_seats} seats</h2>
              </div>
              {playing && (
                <span className={styles.statusPill} data-status={match.status}>
                  Hand {match.hand_number}{match.level_remaining_seconds !== null ? ` · level ${match.level_number} · ${formatDuration(match.level_remaining_seconds)}` : ""}
                </span>
              )}
            </div>
            <table className={styles.rosterTable}>
              <thead>
                <tr><th>Player</th><th>Account</th><th>Seat</th><th>Chips</th><th>Status</th><th /></tr>
              </thead>
              <tbody>
                {match.entries.map((entry) => {
                  const health = entryHealth(entry, now);
                  return (
                    <tr key={entry.entry_id}>
                      <td>
                        <span className={styles.kindTag} data-kind={entry.kind}>{entry.kind === "bot" ? "Bot" : "Human"}</span>{" "}
                        <strong>{entry.display_name}</strong>
                        {entry.bot_endpoint && <small>{entry.bot_endpoint}</small>}
                      </td>
                      <td>{entry.account_email ?? "—"}</td>
                      <td>{entry.seat ?? "—"}</td>
                      <td>{entry.stack !== null ? formatChips(entry.stack) : "—"}</td>
                      <td><span className={styles.health} data-tone={health.tone}>{health.text}</span></td>
                      <td>
                        {match.status === "lobby" && (
                          <button
                            className={styles.textButton}
                            disabled={busy !== null}
                            onClick={() => {
                              if (window.confirm(`Remove ${entry.display_name} from the lobby?`)) {
                                void run("kick", () => kickEntry(matchId, entry.entry_id), `${entry.display_name} removed.`);
                              }
                            }}
                            type="button"
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {match.entries.length === 0 && (
                  <tr><td colSpan={6}>Nobody has joined yet. Share the code above.</td></tr>
                )}
              </tbody>
            </table>
            {match.standings.length > 0 && (
              <>
                <h3 className={styles.subheading}>{over ? "Final standings" : "Eliminated"}</h3>
                <ol className={styles.standings}>
                  {match.standings.map((item) => (
                    <li key={item.entry_id}>
                      <b>{item.position}</b> {item.display_name}
                      <small>{item.final_stack > 0 ? `${formatChips(item.final_stack)} chips` : `out on hand ${item.eliminated_hand_number ?? "—"}`}</small>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </section>
        </div>

        {match.status !== "lobby" && match.status !== "cancelled" && (
          <section className={styles.spectator} aria-label="Spectator view">
            <p className={styles.sectionLabel}>Spectator view · hole cards hidden</p>
            <PokerTable embedded exitHref="/admin" matchId={matchId} mode="spectator" />
          </section>
        )}
      </div>
    </main>
  );
}
