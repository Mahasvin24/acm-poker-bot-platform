"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { CodeEntry } from "../match/join-match";
import { formatChipDelta } from "../match/format";
import {
  changeEmail,
  changePassword,
  createBot,
  deleteAccount,
  getBotToken,
  getLeaderboard,
  listBots,
  logoutAccount,
  myMatches,
  updateBot,
  updateProfile,
  verifyBot,
} from "./api";
import styles from "./account.module.css";
import {
  MATCH_STATUS_LABELS,
  type BotProfile,
  type LeaderboardEntry,
  type MyMatch,
} from "./types";
import { useAccount } from "./use-account";

function TokenField({ botId, initialToken }: { botId: string; initialToken: string | null }) {
  const [token, setToken] = useState(initialToken);
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const toggle = async () => {
    if (visible) {
      setVisible(false);
      setMessage(null);
      return;
    }
    setLoading(true);
    setMessage(null);
    try {
      if (!token) setToken((await getBotToken(botId)).bearer_token);
      setVisible(true);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Could not load your token. Try again.");
    } finally {
      setLoading(false);
    }
  };


  return (
    <div className={styles.field}>
      <label htmlFor={`token-${botId}`}>Bot token</label>
      <div className={styles.tokenField}>
        <input
          autoComplete="off"
          id={`token-${botId}`}
          readOnly
          spellCheck={false}
          type={visible ? "text" : "password"}
          value={visible && token ? token : "hidden-token"}
          aria-describedby={`token-help-${botId}`}
        />
        <button aria-controls={`token-${botId}`} aria-pressed={visible} className={styles.secondaryButton} disabled={loading} onClick={() => void toggle()} type="button">
          {loading ? "Loading…" : visible ? "Hide" : "Show"}
        </button>
      </div>
      <p className={styles.fieldHint} id={`token-help-${botId}`}>Paste this into your starter as BOT_TOKEN, then start your bot.</p>
      {message && <p className={styles.fieldHint} role="status">{message}</p>}
    </div>
  );
}

function BotCard({ bot, initialToken, onChange }: { bot: BotProfile; initialToken: string | null; onChange: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const testing = busy === "verify";
  const testFailure = testError ?? bot.last_verification_error;
  const testPassed = Boolean(bot.verified_at) && !testFailure;

  const run = async (label: string, operation: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    setSaved(false);
    setTestError(null);
    try {
      await operation();
      await onChange();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "That did not work.";
      if (label === "verify") setTestError(message);
      else setError(message);
      await onChange().catch(() => undefined);
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
      setSaved(true);
    });
  };


  return (
    <article className={styles.botCard}>
      <div className={styles.botCardHead}>
        <div>
          <h3>{bot.name}</h3>
          <code>{bot.ip}:{bot.port}</code>
        </div>
        <span className={styles.statusPill} data-status={testPassed ? "running" : "closed"}>
          {testing ? "Testing…" : testPassed ? "Test passed" : testFailure ? "Test failed" : "Test required"}
        </span>
      </div>
      <div className={styles.connectionStatus} aria-live="polite" aria-busy={testing} data-state={testing ? "pending" : testPassed ? "success" : testFailure ? "error" : "pending"}>
        <strong>{testing ? "Checking health and token…" : testPassed ? "Connection test passed" : testFailure ? "Connection test failed" : "Finish setup, then test your bot"}</strong>
        <p>{testing ? "Contacting your bot from the event server." : testPassed ? "Your bot is responding and the token works. You’re ready to join a match!" : testFailure ?? "Fill in your bot’s details, copy the token into your starter, and fire it up. Then give it a test."}</p>
        {testPassed && bot.verified_at && !testing && <p>Last passed: <time dateTime={bot.verified_at}>{new Date(bot.verified_at).toLocaleString()}</time>.</p>}
      </div>
      <form className={styles.form} id={`bot-settings-${bot.id}`} onSubmit={saveEndpoint}>
        <fieldset disabled={!editing || busy !== null}>
          <div className={styles.inlineFields}>
            <div className={styles.field}>
              <label htmlFor={`name-${bot.id}`}>Bot name (required)</label>
              <input defaultValue={bot.name} id={`name-${bot.id}`} maxLength={80} name="name" required />
            </div>
            <div className={styles.field}>
              <label htmlFor={`ip-${bot.id}`}>LAN IP address (required)</label>
              <input defaultValue={bot.ip} id={`ip-${bot.id}`} inputMode="decimal" name="ip" required spellCheck={false} />
            </div>
            <div className={styles.field}>
              <label htmlFor={`port-${bot.id}`}>Port (required)</label>
              <input defaultValue={bot.port} id={`port-${bot.id}`} max={65535} min={1024} name="port" required type="number" />
            </div>
          </div>
        </fieldset>
        <p className={saved ? styles.successMessage : styles.fieldHint} role={saved ? "status" : undefined}>
          {saved ? "Bot settings saved. Test again if you changed the IP or port." : editing ? "Save your changes before testing. Your token stays the same." : "Changing the IP or port needs another test. Your token stays the same."}
        </p>

      </form>
      <TokenField botId={bot.id} initialToken={initialToken} />
      <div className={styles.panelActions}>
        <button className={styles.secondaryButton} disabled={busy !== null || editing} onClick={() => { setEditing(true); setSaved(false); }} type="button">Edit</button>
        <button className={styles.secondaryButton} disabled={busy !== null || !editing} form={`bot-settings-${bot.id}`} type="submit">{busy === "save" ? "Saving…" : "Save"}</button>
        <button
          className={styles.primaryButton}
          disabled={busy !== null || editing}
          onClick={() => void run("verify", async () => { await verifyBot(bot.id); })}
          type="button"
        >
          {testing ? "Testing…" : "Test"}
        </button>
        <a
          className={styles.secondaryButton}
          href={`/dashboard/bots/${encodeURIComponent(bot.id)}/diagnostics`}
          target={`bot-diagnostics-${bot.id}`}
          onClick={(event) => {
            const popup = window.open(event.currentTarget.href, `bot-diagnostics-${bot.id}`, "popup,width=820,height=640");
            if (popup) event.preventDefault();
          }}
        >
          Diagnostics
        </a>
      </div>
      {error && <p className={styles.formError} role="alert">{error}</p>}

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
    <details className={styles.sidebarCard} open={account.participant_kind !== "bot"}>
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
  const [newToken, setNewToken] = useState<{ botId: string; value: string } | null>(null);
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
      setNewToken({ botId: created.bot.id, value: created.bearer_token });
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
    <main className={`${styles.page} ${account.participant_kind === "bot" ? styles.botDashboard : ""}`} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>{account.participant_kind === "bot" ? "Bot Dashboard" : "Player Dashboard"}</span>
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
            <h1>{account.participant_kind === "bot" ? "Connect your bot." : account.participant_kind === "human" ? "Take your seat." : <>Play it.<br /><em>Or code it.</em></>}</h1>
          </div>
          <p>
            {account.participant_kind === "bot"
              ? "Configure your bot, pass a connection test, then join a match with the organizer’s code."
              : account.participant_kind === "human"
                ? "Enter a match code from the organizer to play in your browser."
                : "Enter a match code to play yourself or seat a bot. Your saved bots can be reused in every match."}
          </p>
        </section>

        <div className={styles.workspace}>
          <aside className={styles.sidebar}>
            <section className={styles.sidebarCard}>
              <h2>Join a match</h2>
              <p>Codes look like K7Q-4PM.</p>
              <CodeEntry compact />
            </section>
            {account.participant_kind !== "bot" && <section className={styles.sidebarCard}>
              <h2>Practice</h2>
              <p>Play a full hand against three built-in bots. Nothing is saved.</p>
              <div className={styles.panelActions} style={{ marginTop: 16 }}>
                <Link className={styles.textButton} href="/demo">Open the demo ↗</Link>
              </div>
            </section>}
            {account.participant_kind !== "bot" && <>
            <ProfileCard
              account={account}
              onChange={async () => {
                await refresh();
                await reloadAccount();
              }}
            />
            <PasswordCard />
            </>}
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
            {account.participant_kind !== "human" && <section className={styles.panel} id="bots">
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.sectionLabel}>Bots</p>
                  <h2>Bot configuration</h2>
                  <p className={styles.panelIntro}>
                    All three fields are required. One account, one bot. Save your settings, copy the token into your starter, and try a connection test.{" "}
                    <Link href="/bot-guide">Read the protocol guide</Link>.
                  </p>
                </div>
              </div>
              {bots === null ? <p className={styles.panelIntro}>Loading saved bots…</p> : <>
              {bots.length === 0 && <form className={styles.form} onSubmit={(event) => void addBot(event)}>
                <div className={styles.inlineFields}>
                  <div className={styles.field}>
                    <label htmlFor="bot-name">Bot name (required)</label>
                    <input id="bot-name" maxLength={80} name="name" placeholder="e.g. RiverRunner" required />
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="bot-ip">LAN IP address (required)</label>
                    <input id="bot-ip" inputMode="decimal" name="ip" placeholder="e.g. 192.168.1.42" required spellCheck={false} />
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="bot-port">Port (required)</label>
                    <input defaultValue={8001} id="bot-port" max={65535} min={1024} name="port" required type="number" />
                  </div>
                </div>
                <p className={styles.fieldHint}>A successful connection test is required before joining a match. Use your laptop’s address on the event Wi-Fi, not localhost. Port 8001 matches both starters. Saving generates the BOT_TOKEN your starter needs.</p>
                <div className={styles.panelActions}>
                  <button className={styles.secondaryButton} disabled={busy} type="submit">{busy ? "Saving…" : "Save"}</button>
                </div>
              </form>}
              {error && <p className={styles.formError} role="alert">{error}</p>}
              <div className={styles.botList}>
                {bots.map((bot) => <div key={bot.id}>
                  <BotCard bot={bot} initialToken={newToken?.botId === bot.id ? newToken.value : null} onChange={refresh} />
                </div>)}
              </div>
              </>}
            </section>}

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
          </div>
        </div>
      </div>
    </main>
  );
}
