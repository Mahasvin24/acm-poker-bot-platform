"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { CodeEntry } from "../match/join-match";
import { relativeTime } from "../match/format";
import { formatChipDelta } from "../match/format";
import {
  changeEmail,
  changePassword,
  createBot,
  deleteAccount,
  deleteBot,
  getBotDiagnostics,
  getLeaderboard,
  listBots,
  logoutAccount,
  myMatches,
  rotateBotToken,
  updateBot,
  updateProfile,
  verifyBot,
} from "./api";
import styles from "./account.module.css";
import {
  MATCH_STATUS_LABELS,
  type BotDiagnostics,
  type BotProfile,
  type LeaderboardEntry,
  type MyMatch,
} from "./types";
import { useAccount } from "./use-account";

function TokenReveal({ token, onDismiss }: { token: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState<string | null>(null);
  const copy = async () => {
    try {
      if (!navigator.clipboard) throw new Error("unavailable");
      await navigator.clipboard.writeText(token);
      setCopied("Copied. Paste it into your bot as BOT_TOKEN.");
    } catch {
      setCopied("Select the token and copy it manually.");
    }
  };
  return (
    <div className={styles.tokenBox}>
      <span className={styles.tokenLabel}>Shown once · Save this bearer token</span>
      <code translate="no">{token}</code>
      <div className={styles.tokenActions}>
        <button className={styles.copyButton} onClick={() => void copy()} type="button">Copy Token</button>
        <button className={styles.textButton} onClick={onDismiss} type="button">I saved it</button>
      </div>
      {copied && <p className={styles.fieldHint}>{copied}</p>}
    </div>
  );
}

function BotCard({ bot, onChange }: { bot: BotProfile; onChange: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [diagnostics, setDiagnostics] = useState<{ data: BotDiagnostics; loadedAt: number } | null>(null);

  const run = async (label: string, operation: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await operation();
      await onChange();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That did not work.");
      await onChange();
    } finally {
      setBusy(null);
    }
  };

  const saveEndpoint = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run("save", async () => {
      await updateBot(bot.id, {
        name: String(form.get("name") ?? "").trim(),
        ip: String(form.get("ip") ?? "").trim(),
        port: Number(form.get("port")),
      });
      setEditing(false);
    });
  };

  const loadDiagnostics = async () => {
    if (diagnostics) {
      setDiagnostics(null);
      return;
    }
    try {
      setDiagnostics({ data: await getBotDiagnostics(bot.id), loadedAt: Date.now() });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Diagnostics are unavailable.");
    }
  };

  return (
    <article className={styles.botCard}>
      <div className={styles.botCardHead}>
        <div>
          <h3>{bot.name}</h3>
          <code>{bot.ip}:{bot.port}</code>
        </div>
        <span className={styles.statusPill} data-status={bot.verified_at ? "running" : "closed"}>
          {bot.verified_at ? "Ready" : "Not verified"}
        </span>
      </div>
      {bot.last_verification_error && !bot.verified_at && (
        <p className={styles.formError}>{bot.last_verification_error}</p>
      )}
      {token && <TokenReveal onDismiss={() => setToken(null)} token={token} />}
      {editing && (
        <form className={styles.form} onSubmit={saveEndpoint}>
          <div className={styles.inlineFields}>
            <div className={styles.field}>
              <label htmlFor={`name-${bot.id}`}>Name</label>
              <input defaultValue={bot.name} id={`name-${bot.id}`} maxLength={80} name="name" required />
            </div>
            <div className={styles.field}>
              <label htmlFor={`ip-${bot.id}`}>LAN IP</label>
              <input defaultValue={bot.ip} id={`ip-${bot.id}`} inputMode="decimal" name="ip" required spellCheck={false} />
            </div>
            <div className={styles.field}>
              <label htmlFor={`port-${bot.id}`}>Port</label>
              <input defaultValue={bot.port} id={`port-${bot.id}`} max={65535} min={1024} name="port" required type="number" />
            </div>
          </div>
          <p className={styles.fieldHint}>Changing the address requires verifying again. Your token stays the same.</p>
          <div className={styles.panelActions}>
            <button className={styles.secondaryButton} disabled={busy !== null} type="submit">Save</button>
            <button className={styles.textButton} onClick={() => setEditing(false)} type="button">Cancel</button>
          </div>
        </form>
      )}
      <div className={styles.panelActions}>
        <button
          className={styles.primaryButton}
          disabled={busy !== null}
          onClick={() => void run("verify", async () => { await verifyBot(bot.id); })}
          type="button"
        >
          {busy === "verify" ? "Contacting bot…" : bot.verified_at ? "Verify Again" : "Verify Connection"}
        </button>
        <button className={styles.secondaryButton} disabled={busy !== null} onClick={() => setEditing((value) => !value)} type="button">Edit</button>
        <button
          className={styles.secondaryButton}
          disabled={busy !== null}
          onClick={() => void run("rotate", async () => { setToken((await rotateBotToken(bot.id)).bearer_token); })}
          type="button"
        >
          New Token
        </button>
        <button className={styles.secondaryButton} onClick={() => void loadDiagnostics()} type="button">
          {diagnostics ? "Hide Diagnostics" : "Diagnostics"}
        </button>
        <button
          className={styles.textButton}
          disabled={busy !== null}
          onClick={() => {
            if (window.confirm(`Delete ${bot.name}? Seats it already holds keep playing with automatic actions.`)) {
              void run("delete", async () => { await deleteBot(bot.id); });
            }
          }}
          type="button"
        >
          Delete
        </button>
      </div>
      {error && <p className={styles.formError} role="alert">{error}</p>}
      {diagnostics && (
        <div className={styles.diagnostics}>
          <p>
            {diagnostics.data.decisions} decisions this session ·{" "}
            {Object.values(diagnostics.data.failures).reduce((total, count) => total + count, 0)} automatic fallbacks
            {diagnostics.data.consecutive_failures >= 3 ? " · health-check mode (bot looks unreachable)" : ""}
          </p>
          {diagnostics.data.recent.length === 0 ? (
            <p>No decisions yet. They appear here once your bot plays a hand.</p>
          ) : (
            <ol>
              {diagnostics.data.recent.slice(0, 12).map((item) => (
                <li data-failed={item.failure_reason ? "true" : undefined} key={`${item.hand_id}-${item.at}`}>
                  <span>{relativeTime(item.at, diagnostics.loadedAt)}</span>
                  <strong>{item.failure_reason ? `${item.action} (automatic)` : `${item.action}${item.amount_to ? ` to ${item.amount_to}` : ""}`}</strong>
                  <small>{item.latency_ms} ms</small>
                  {item.explanation && <p>{item.explanation}</p>}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </article>
  );
}

function ProfileCard({
  account,
  onChange,
}: {
  account: import("./types").Account;
  onChange: () => Promise<void>;
}) {
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const saveName = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("display_name") ?? "").trim();
    try {
      await updateProfile(name || null);
      await onChange();
      setMessage({ ok: true, text: "Profile updated." });
    } catch (reason) {
      setMessage({ ok: false, text: reason instanceof Error ? reason.message : "Update failed." });
    }
  };
  const saveEmail = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      await changeEmail(String(data.get("current")), String(data.get("email")).trim());
      await onChange();
      setMessage({ ok: true, text: "Email updated." });
    } catch (reason) {
      setMessage({ ok: false, text: reason instanceof Error ? reason.message : "Email change failed." });
    }
  };
  const remove = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const password = String(new FormData(event.currentTarget).get("delete_password") ?? "");
    if (!window.confirm("Delete your account permanently? This cannot be undone.")) return;
    try {
      await deleteAccount(password);
      window.location.href = "/account";
    } catch (reason) {
      setMessage({ ok: false, text: reason instanceof Error ? reason.message : "Delete failed." });
    }
  };
  return (
    <details className={styles.sidebarCard} open>
      <summary className={styles.summaryToggle}>Your account</summary>
      <div className={styles.form}>
        <p className={styles.fieldHint}>
          Career total: {formatChipDelta(account.career_chip_total)} across {account.matches_finished} finished match{account.matches_finished === 1 ? "" : "es"}.
        </p>
        <form className={styles.form} onSubmit={(event) => void saveName(event)}>
          <div className={styles.field}>
            <label htmlFor="profile-name">Default table name</label>
            <input defaultValue={account.display_name ?? ""} id="profile-name" maxLength={80} name="display_name" placeholder="Used when you join a match" />
          </div>
          <button className={styles.secondaryButton} type="submit">Save name</button>
        </form>
        <form className={styles.form} onSubmit={(event) => void saveEmail(event)}>
          <div className={styles.field}>
            <label htmlFor="profile-email-current">Current password</label>
            <input id="profile-email-current" name="current" required type="password" />
          </div>
          <div className={styles.field}>
            <label htmlFor="profile-email">New email</label>
            <input defaultValue={account.email} id="profile-email" name="email" required type="email" />
          </div>
          <button className={styles.secondaryButton} type="submit">Change email</button>
        </form>
        <form className={styles.form} onSubmit={(event) => void remove(event)}>
          <div className={styles.field}>
            <label htmlFor="delete-password">Delete account</label>
            <input id="delete-password" name="delete_password" placeholder="Confirm with password" required type="password" />
          </div>
          <button className={styles.textButton} type="submit">Delete my account</button>
        </form>
        {message && <p className={message.ok ? styles.successMessage : styles.formError}>{message.text}</p>}
      </div>
    </details>
  );
}

function PasswordCard() {
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      await changePassword(String(data.get("current")), String(data.get("next")));
      form.reset();
      setMessage({ ok: true, text: "Password updated." });
    } catch (reason) {
      setMessage({ ok: false, text: reason instanceof Error ? reason.message : "Password change failed." });
    }
  };
  return (
    <details className={styles.sidebarCard}>
      <summary className={styles.summaryToggle}>Change password</summary>
      <form className={styles.form} onSubmit={(event) => void submit(event)}>
        <div className={styles.field}>
          <label htmlFor="pw-current">Current password</label>
          <input autoComplete="current-password" id="pw-current" name="current" required type="password" />
        </div>
        <div className={styles.field}>
          <label htmlFor="pw-next">New password</label>
          <input autoComplete="new-password" id="pw-next" minLength={10} name="next" required type="password" />
        </div>
        <button className={styles.secondaryButton} type="submit">Update</button>
        {message && <p className={message.ok ? styles.successMessage : styles.formError}>{message.text}</p>}
      </form>
    </details>
  );
}

export function ParticipantDashboard() {
  const router = useRouter();
  const { account, error: accountError, reload: reloadAccount } = useAccount("/dashboard");
  const [matches, setMatches] = useState<MyMatch[] | null>(null);
  const [bots, setBots] = useState<BotProfile[] | null>(null);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[] | null>(null);

  const refresh = useCallback(async () => {
    const [nextMatches, nextBots, board] = await Promise.all([
      myMatches(),
      listBots(),
      getLeaderboard().catch(() => [] as LeaderboardEntry[]),
    ]);
    setMatches(nextMatches);
    setBots(nextBots);
    setLeaderboard(board);
  }, []);

  useEffect(() => {
    if (!account) return;
    if (account.role === "admin") {
      router.replace("/admin");
      return;
    }
    const timer = window.setTimeout(() => {
      refresh().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load your matches."));
    }, 0);
    const interval = window.setInterval(() => void refresh().catch(() => undefined), 5_000);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(interval);
    };
  }, [account, refresh, router]);

  const addBot = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError(null);
    try {
      const created = await createBot(
        String(data.get("name") ?? "").trim(),
        String(data.get("ip") ?? "").trim(),
        Number(data.get("port")),
      );
      setNewToken(created.bearer_token);
      form.reset();
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not add the bot.");
    } finally {
      setBusy(false);
    }
  };

  if (!account) {
    return (
      <main className={styles.page} id="main-content">
        <div className={styles.loading}><span>{accountError ?? "Loading your account"}</span></div>
      </main>
    );
  }

  const live = matches?.filter((item) => item.status !== "completed" && item.status !== "cancelled") ?? [];
  const past = matches?.filter((item) => item.status === "completed" || item.status === "cancelled") ?? [];

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Player Dashboard</span>
        <div className={styles.headerAccount}>
          <span>{account.email}</span>
          <button className={styles.textButton} onClick={() => void logoutAccount().finally(() => router.replace("/account"))} type="button">
            Sign Out
          </button>
        </div>
      </header>

      <div className={styles.dashboard}>
        <section className={styles.dashboardIntro}>
          <div>
            <p className={styles.eyebrow}>Your seat</p>
            <h1>Play it.<br /><em>Or code it.</em></h1>
          </div>
          <p>
            Enter a match code from the organizer to sit down yourself or seat one of your bots.
            Bots you add here can be reused in every match.
          </p>
        </section>

        <div className={styles.workspace}>
          <aside className={styles.sidebar}>
            <section className={styles.sidebarCard}>
              <h2>Join a match</h2>
              <p>Codes look like K7Q-4PM.</p>
              <CodeEntry compact />
            </section>
            <section className={styles.sidebarCard}>
              <h2>Practice</h2>
              <p>Play a full hand against three built-in bots. Nothing is saved.</p>
              <div className={styles.panelActions} style={{ marginTop: 16 }}>
                <Link className={styles.textButton} href="/demo">Open the demo ↗</Link>
              </div>
            </section>
            <ProfileCard
              account={account}
              onChange={async () => {
                await refresh();
                await reloadAccount();
              }}
            />
            <PasswordCard />
            {leaderboard && leaderboard.length > 0 && (
              <section className={styles.sidebarCard}>
                <h2>Event leaderboard</h2>
                <ol className={styles.standings}>
                  {leaderboard.slice(0, 8).map((item, index) => (
                    <li key={item.account_id}>
                      <b>{index + 1}</b>
                      {item.display_name ?? item.email.split("@")[0]}
                      <small>{formatChipDelta(item.career_chip_total)} · {item.matches_finished} matches</small>
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </aside>

          <div className={styles.stack}>
            <section className={styles.panel}>
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.sectionLabel}>Matches</p>
                  <h2>Your matches</h2>
                </div>
              </div>
              {matches === null ? (
                <p className={styles.panelIntro}>Loading…</p>
              ) : live.length === 0 && past.length === 0 ? (
                <p className={styles.panelIntro}>You haven’t joined a match yet. Enter a code to get started.</p>
              ) : (
                <ul className={styles.matchList}>
                  {[...live, ...past].map((item) => {
                    const result = item.my_entries.find((entry) => entry.chip_delta !== null);
                    return (
                    <li key={item.match_id}>
                      <div>
                        <strong>{item.name}</strong>
                        <small>
                          {item.my_entries.map((entry) => `${entry.display_name}${entry.kind === "bot" ? " (bot)" : ""}`).join(", ")}
                          {" · "}{item.seats_taken}/{item.max_seats} seats
                          {result?.finish_position != null && (
                            <> · #{result.finish_position}{result.chip_delta != null ? ` · ${formatChipDelta(result.chip_delta)}` : ""}</>
                          )}
                        </small>
                      </div>
                      <span className={styles.statusPill} data-status={item.status}>{MATCH_STATUS_LABELS[item.status]}</span>
                      <Link className={item.status === "running" ? styles.primaryButton : styles.secondaryButton} href={`/match/${item.match_id}`}>
                        {item.status === "lobby" ? "Lobby" : item.status === "completed" || item.status === "cancelled" ? "Results" : "Open Table"}
                      </Link>
                    </li>
                    );
                  })}
                </ul>
              )}
            </section>

            <section className={styles.panel} id="bots">
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.sectionLabel}>Bots</p>
                  <h2>My bots</h2>
                  <p className={styles.panelIntro}>
                    Run your bot on your laptop, then register its LAN address here.{" "}
                    <Link href="/bot-guide">Read the protocol guide</Link>.
                  </p>
                </div>
              </div>
              {newToken && <div className={styles.entrantBody}><TokenReveal onDismiss={() => setNewToken(null)} token={newToken} /></div>}
              <form className={styles.form} onSubmit={(event) => void addBot(event)}>
                <div className={styles.inlineFields}>
                  <div className={styles.field}>
                    <label htmlFor="bot-name">Bot name</label>
                    <input id="bot-name" maxLength={80} name="name" placeholder="e.g. RiverRunner" required />
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="bot-ip">LAN IP address</label>
                    <input id="bot-ip" inputMode="decimal" name="ip" placeholder="e.g. 192.168.1.42" required spellCheck={false} />
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="bot-port">Port</label>
                    <input defaultValue={8001} id="bot-port" max={65535} min={1024} name="port" required type="number" />
                  </div>
                </div>
                <p className={styles.fieldHint}>Use your laptop’s address on the event Wi-Fi, not localhost. You’ll get a one-time token for the bot.</p>
                {error && <p className={styles.formError} role="alert">{error}</p>}
                <button className={styles.secondaryButton} disabled={busy} type="submit">{busy ? "Adding…" : "Add Bot"}</button>
              </form>
              <div className={styles.botList}>
                {bots?.map((bot) => <BotCard bot={bot} key={bot.id} onChange={refresh} />)}
              </div>
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
