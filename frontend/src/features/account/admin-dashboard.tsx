"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createMatch,
  listAccounts,
  listAdminMatches,
  logoutAccount,
  resetPassword,
} from "./api";
import styles from "./account.module.css";
import {
  DEFAULT_MATCH_CONFIG,
  MATCH_STATUS_LABELS,
  type Account,
  type AdminMatchSummary,
  type MatchConfig,
} from "./types";
import { useAccount } from "./use-account";

function AccountsCard() {
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [filter, setFilter] = useState("");
  const [reset, setReset] = useState<{ email: string; password: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setAccounts(await listAccounts());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load accounts.");
    }
  };

  const doReset = async (account: Account) => {
    if (!window.confirm(`Reset the password for ${account.email}? They will be signed out everywhere.`)) return;
    try {
      const result = await resetPassword(account.id);
      setReset({ email: account.email, password: result.temporary_password });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Reset failed.");
    }
  };

  const shown = accounts?.filter((item) => item.email.includes(filter.trim().toLowerCase())) ?? [];
  return (
    <details className={styles.sidebarCard} onToggle={(event) => { if ((event.target as HTMLDetailsElement).open && !accounts) void load(); }}>
      <summary className={styles.summaryToggle}>Accounts &amp; password resets</summary>
      <div className={styles.form}>
        <div className={styles.field}>
          <label htmlFor="account-filter">Find by email</label>
          <input id="account-filter" onChange={(event) => setFilter(event.target.value)} value={filter} />
        </div>
        {reset && (
          <div className={styles.tokenBox}>
            <span className={styles.tokenLabel}>Temporary password for {reset.email}</span>
            <code>{reset.password}</code>
            <p className={styles.fieldHint}>Share it privately. They can change it from their dashboard.</p>
          </div>
        )}
        {error && <p className={styles.formError}>{error}</p>}
        <ul className={styles.accountList}>
          {shown.slice(0, 30).map((item) => (
            <li key={item.id}>
              <span>{item.email}{item.role === "admin" ? " · admin" : ""}</span>
              {item.role !== "admin" && (
                <button className={styles.textButton} onClick={() => void doReset(item)} type="button">Reset</button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

export function AdminDashboard() {
  const router = useRouter();
  const { account, error: accountError } = useAccount("/admin");
  const [matches, setMatches] = useState<AdminMatchSummary[] | null>(null);
  const [escalate, setEscalate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setMatches(await listAdminMatches());
  }, []);

  useEffect(() => {
    if (!account) return;
    if (account.role !== "admin") {
      router.replace("/dashboard");
      return;
    }
    const timer = window.setTimeout(() => void refresh().catch(() => undefined), 0);
    const interval = window.setInterval(() => void refresh().catch(() => undefined), 3_000);
    return () => {
      window.clearTimeout(timer);
      window.clearInterval(interval);
    };
  }, [account, refresh, router]);

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const config: MatchConfig = {
      max_seats: Number(data.get("seats")),
      starting_stack: Number(data.get("stack")),
      small_blind: Number(data.get("sb")),
      big_blind: Number(data.get("bb")),
      big_blind_ante: data.get("ante") === "on",
      human_action_timeout_ms: Number(data.get("clock")) * 1000,
      blind_increase_minutes: escalate ? Number(data.get("levelMinutes")) : null,
    };
    setBusy(true);
    setError(null);
    try {
      const created = await createMatch(String(data.get("name") ?? "").trim(), config);
      router.push(`/admin/match/${created.match_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not create the match.");
      setBusy(false);
    }
  };

  if (!account || account.role !== "admin") {
    return (
      <main className={styles.page} id="main-content">
        <div className={styles.loading}><span>{accountError ?? "Loading admin account"}</span></div>
      </main>
    );
  }

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Match Director</span>
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
            <p className={styles.eyebrow}>Admin console</p>
            <h1>Deal a<br /><em>match.</em></h1>
          </div>
          <p>
            Create a match, share its code, and start when everyone is seated. Humans join in the
            browser; bot builders seat a verified bot.
          </p>
        </section>

        <div className={styles.workspace}>
          <aside className={styles.sidebar}>
            <section className={styles.sidebarCard}>
              <h2>New match</h2>
              <form className={styles.form} onSubmit={(event) => void create(event)}>
                <div className={styles.field}>
                  <label htmlFor="match-name">Name</label>
                  <input id="match-name" maxLength={80} name="name" placeholder="e.g. Friday Table 1" required />
                </div>
                <div className={styles.inlineFields}>
                  <div className={styles.field}>
                    <label htmlFor="match-seats">Seats</label>
                    <select defaultValue={DEFAULT_MATCH_CONFIG.max_seats} id="match-seats" name="seats">
                      {[2, 3, 4, 5, 6].map((count) => <option key={count} value={count}>{count}</option>)}
                    </select>
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="match-stack">Starting chips</label>
                    <input defaultValue={DEFAULT_MATCH_CONFIG.starting_stack} id="match-stack" min={1} name="stack" required type="number" />
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="match-sb">Small blind</label>
                    <input defaultValue={DEFAULT_MATCH_CONFIG.small_blind} id="match-sb" min={1} name="sb" required type="number" />
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="match-bb">Big blind</label>
                    <input defaultValue={DEFAULT_MATCH_CONFIG.big_blind} id="match-bb" min={2} name="bb" required type="number" />
                  </div>
                  <div className={styles.field}>
                    <label htmlFor="match-clock">Seconds per decision</label>
                    <input defaultValue={DEFAULT_MATCH_CONFIG.human_action_timeout_ms / 1000} id="match-clock" max={300} min={5} name="clock" required type="number" />
                  </div>
                  {escalate && (
                    <div className={styles.field}>
                      <label htmlFor="match-level">Minutes per level</label>
                      <input defaultValue={10} id="match-level" max={120} min={1} name="levelMinutes" required type="number" />
                    </div>
                  )}
                </div>
                <label className={styles.checkRow}>
                  <input checked={escalate} onChange={(event) => setEscalate(event.target.checked)} type="checkbox" />
                  Blinds rise over time
                </label>
                <label className={styles.checkRow}>
                  <input name="ante" type="checkbox" />
                  Big-blind ante
                </label>
                {error && <p className={styles.formError} role="alert">{error}</p>}
                <button className={styles.primaryButton} disabled={busy} type="submit">{busy ? "Creating…" : "Create & Get Code"}</button>
              </form>
            </section>
            <AccountsCard />
          </aside>

          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <div>
                <p className={styles.sectionLabel}>All matches</p>
                <h2>Matches</h2>
                <p className={styles.panelIntro}>Updates every few seconds.</p>
              </div>
            </div>
            {matches === null ? (
              <p className={styles.panelIntro}>Loading…</p>
            ) : matches.length === 0 ? (
              <p className={styles.panelIntro}>No matches yet. Create one to get a join code.</p>
            ) : (
              <ul className={styles.matchList}>
                {matches.map((item) => (
                  <li key={item.match_id}>
                    <div>
                      <strong>{item.name}</strong>
                      <small>
                        {item.join_code ? `Code ${item.join_code} · ` : ""}
                        {item.status === "lobby" ? `${item.seats_taken}/${item.max_seats} joined` : `${item.players_remaining} of ${item.seats_taken} left`}
                      </small>
                    </div>
                    <span className={styles.statusPill} data-status={item.status}>{MATCH_STATUS_LABELS[item.status]}</span>
                    <Link className={styles.secondaryButton} href={`/admin/match/${item.match_id}`}>Manage</Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
