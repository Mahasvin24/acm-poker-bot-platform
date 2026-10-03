"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import {
  AccountApiError,
  configureBot,
  getEntrant,
  getMe,
  logoutAccount,
  registerEntrant,
  verifyBot,
} from "./api";
import styles from "./account.module.css";
import type { Account, Entrant, EntrantKind } from "./types";

interface ParticipantDashboardProps {
  initialTournamentId: string;
}

export function ParticipantDashboard({ initialTournamentId }: ParticipantDashboardProps) {
  const router = useRouter();
  const [account, setAccount] = useState<Account | null>(null);
  const [tournamentId, setTournamentId] = useState(initialTournamentId);
  const [activeTournamentId, setActiveTournamentId] = useState(initialTournamentId);
  const [entrant, setEntrant] = useState<Entrant | null>(null);
  const [lookupComplete, setLookupComplete] = useState(false);
  const [kind, setKind] = useState<EntrantKind>("human");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [bearerToken, setBearerToken] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const current = await getMe();
        if (!active) return;
        setAccount(current);
        if (current.role === "admin") {
          router.replace("/admin");
          return;
        }
        if (initialTournamentId) {
          try {
            const currentEntrant = await getEntrant(initialTournamentId);
            if (active) setEntrant(currentEntrant);
          } catch (requestError) {
            if (!(requestError instanceof AccountApiError && requestError.status === 404)) {
              throw requestError;
            }
          }
          if (active) setLookupComplete(true);
        }
      } catch (requestError) {
        if (!active) return;
        if (requestError instanceof AccountApiError && requestError.status === 401) {
          router.replace("/account");
          return;
        }
        setError("The account service is unavailable. Check that the API is running.");
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [initialTournamentId, router]);

  const findTournament = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = tournamentId.trim();
    if (!normalized) {
      setError("Enter the tournament ID supplied by the organizer.");
      return;
    }
    setBusy("lookup");
    setError(null);
    setNotice(null);
    setBearerToken(null);
    try {
      const current = await getEntrant(normalized);
      setEntrant(current);
    } catch (requestError) {
      if (requestError instanceof AccountApiError && requestError.status === 404) {
        setEntrant(null);
      } else {
        setError(requestError instanceof Error ? requestError.message : "Tournament lookup failed.");
      }
    } finally {
      setActiveTournamentId(normalized);
      setLookupComplete(true);
      router.replace(`/dashboard?tournament=${encodeURIComponent(normalized)}`);
      setBusy(null);
    }
  };

  const joinTournament = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const displayName = String(form.get("displayName") ?? "").trim();
    if (!displayName) {
      setError("Enter the name that should appear at the table.");
      return;
    }
    setBusy("join");
    setError(null);
    try {
      const registered = await registerEntrant(activeTournamentId, kind, displayName);
      setEntrant(registered);
      setNotice(`${kind === "human" ? "Human" : "Bot"} entry registered.`);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Registration failed.");
    } finally {
      setBusy(null);
    }
  };

  const saveBotEndpoint = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const ip = String(form.get("ip") ?? "").trim();
    const port = Number(form.get("port"));
    setBusy("configure");
    setError(null);
    setNotice(null);
    setBearerToken(null);
    try {
      const result = await configureBot(activeTournamentId, ip, port);
      setEntrant(result.entrant);
      setBearerToken(result.bearer_token);
      setNotice("Endpoint saved. Copy the token before leaving this page.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Endpoint setup failed.");
    } finally {
      setBusy(null);
    }
  };

  const runVerification = async () => {
    setBusy("verify");
    setError(null);
    setNotice(null);
    try {
      const verified = await verifyBot(activeTournamentId);
      setEntrant(verified);
      setNotice("Bot verified and ready for seating.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Bot verification failed.");
    } finally {
      setBusy(null);
    }
  };

  const copyToken = async () => {
    if (!bearerToken) return;
    setError(null);
    try {
      if (!navigator.clipboard) throw new Error("Clipboard access is unavailable");
      await navigator.clipboard.writeText(bearerToken);
      setNotice("Bearer token copied.");
    } catch {
      setError("Could not copy automatically. Select the token and copy it manually.");
    }
  };

  const signOut = async () => {
    setBusy("logout");
    try {
      await logoutAccount();
    } finally {
      router.replace("/account");
    }
  };

  if (!account) {
    return (
      <main className={styles.page} id="main-content">
        <div className={styles.loading}><span>{error ?? "Loading Player Account"}</span></div>
      </main>
    );
  }

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Player Dashboard</span>
        <div className={styles.headerAccount}>
          <span>{account.email}</span>
          <button className={styles.textButton} disabled={busy === "logout"} onClick={signOut} type="button">
            Sign Out
          </button>
        </div>
      </header>

      <div className={styles.dashboard}>
        <section className={styles.dashboardIntro}>
          <div>
            <p className={styles.eyebrow}>Participant Control Room</p>
            <h1>Choose your<br /><em>side.</em></h1>
          </div>
          <p>
            Join once as a human or bot. Human players return here to find their table;
            bot builders configure and verify their endpoint before seating.
          </p>
        </section>

        <div className={styles.workspace}>
          <aside className={styles.sidebar}>
            <section className={styles.sidebarCard}>
              <h2>Find Tournament</h2>
              <p>Use the exact ID shared by the organizer.</p>
              <form className={styles.form} onSubmit={findTournament}>
                <div className={styles.field}>
                  <label htmlFor="participant-tournament">Tournament ID</label>
                  <input
                    autoComplete="off"
                    id="participant-tournament"
                    name="tournamentId"
                    onChange={(event) => setTournamentId(event.target.value)}
                    placeholder="e.g. club-event…"
                    spellCheck={false}
                    value={tournamentId}
                  />
                </div>
                <button className={styles.secondaryButton} disabled={busy === "lookup"} type="submit">
                  {busy === "lookup" ? "Checking…" : "Check Entry"}
                </button>
              </form>
            </section>
            <section className={styles.sidebarCard}>
              <h2>Interface Demo</h2>
              <p>Explore the table controls without an account or live tournament.</p>
              <div className={styles.panelActions}>
                <Link className={styles.textButton} href="/play/demo">Open Demo Table ↗</Link>
              </div>
            </section>
          </aside>

          <section aria-live="polite">
            {!lookupComplete ? (
              <div className={styles.emptyState}>
                <p className={styles.sectionLabel}>No Tournament Selected</p>
                <h2>Start with the event ID.</h2>
                <p>Your account may hold one human or bot entry in each tournament.</p>
              </div>
            ) : entrant ? (
              <div className={styles.panel}>
                <div className={styles.panelHead}>
                  <div>
                    <p className={styles.sectionLabel}>{activeTournamentId}</p>
                    <h2>{entrant.kind === "human" ? "Human Entry" : "Bot Entry"}</h2>
                    <p className={styles.panelIntro}>Registration is attached to this account.</p>
                  </div>
                  <span className={styles.statusPill} data-status={entrant.bot_verified_at ? "verified" : "registered"}>
                    {entrant.kind === "bot"
                      ? entrant.bot_verified_at ? "Verified" : "Needs Verification"
                      : "Registered"}
                  </span>
                </div>

                <div className={styles.entrantBody}>
                  <div className={styles.entrantSummary}>
                    <div>
                      <span className={styles.sectionLabel}>Table Name</span>
                      <h3>{entrant.display_name}</h3>
                    </div>
                    <span>{entrant.kind === "bot" ? "API Player" : "Browser Player"}</span>
                  </div>

                  {entrant.kind === "human" ? (
                    <div className={styles.panelActions}>
                      <Link className={styles.primaryButton} href={`/play/${encodeURIComponent(activeTournamentId)}`}>
                        Open My Table →
                      </Link>
                    </div>
                  ) : (
                    <div className={styles.botSetup}>
                      <div>
                        <h3>Bot Endpoint</h3>
                        <p className={styles.panelIntro}>
                          Enter the numeric LAN address and port where your bot is listening.
                        </p>
                      </div>
                      <form className={styles.form} onSubmit={saveBotEndpoint}>
                        <div className={styles.inlineFields}>
                          <div className={styles.field}>
                            <label htmlFor="bot-ip">LAN IP Address</label>
                            <input
                              autoComplete="off"
                              defaultValue={entrant.bot_ip ?? ""}
                              id="bot-ip"
                              inputMode="decimal"
                              name="ip"
                              placeholder="e.g. 192.168.1.42…"
                              required
                              spellCheck={false}
                            />
                          </div>
                          <div className={styles.field}>
                            <label htmlFor="bot-port">Port</label>
                            <input
                              defaultValue={entrant.bot_port ?? 8001}
                              id="bot-port"
                              inputMode="numeric"
                              max={65535}
                              min={1024}
                              name="port"
                              required
                              type="number"
                            />
                          </div>
                        </div>
                        <button className={styles.secondaryButton} disabled={busy === "configure"} type="submit">
                          {busy === "configure" ? "Saving…" : entrant.bot_ip ? "Replace Endpoint & Token" : "Save Endpoint"}
                        </button>
                      </form>

                      {bearerToken && (
                        <div className={styles.tokenBox}>
                          <span className={styles.tokenLabel}>Shown Once · Save This Token</span>
                          <code translate="no">{bearerToken}</code>
                          <div className={styles.tokenActions}>
                            <button className={styles.copyButton} onClick={copyToken} type="button">Copy Token</button>
                          </div>
                        </div>
                      )}

                      <div className={styles.panelActions}>
                        <button
                          className={styles.primaryButton}
                          disabled={!entrant.bot_ip || busy === "verify"}
                          onClick={runVerification}
                          type="button"
                        >
                          {busy === "verify" ? "Contacting Bot…" : "Verify Bot Connection"}
                        </button>
                        <Link className={styles.textButton} href="/bot-guide">Protocol Guide</Link>
                      </div>
                    </div>
                  )}
                  {notice && <p className={styles.successMessage}>{notice}</p>}
                  {error && <p className={styles.formError}>{error}</p>}
                </div>
              </div>
            ) : (
              <div className={styles.panel}>
                <div className={styles.panelHead}>
                  <div>
                    <p className={styles.sectionLabel}>{activeTournamentId}</p>
                    <h2>Register Your Entry</h2>
                    <p className={styles.panelIntro}>This choice is fixed for this tournament.</p>
                  </div>
                  <span className={styles.statusPill} data-status="draft">Not Registered</span>
                </div>
                <form className={styles.form} onSubmit={joinTournament}>
                  <fieldset>
                    <legend className={styles.kindLegend}>Entrant Type</legend>
                    <div className={styles.kindChoices}>
                      <label className={styles.kindChoice}>
                        <input
                          checked={kind === "human"}
                          name="kind"
                          onChange={() => setKind("human")}
                          type="radio"
                          value="human"
                        />
                        <strong>Human</strong>
                        <span>Play every legal action in the browser.</span>
                      </label>
                      <label className={styles.kindChoice}>
                        <input
                          checked={kind === "bot"}
                          name="kind"
                          onChange={() => setKind("bot")}
                          type="radio"
                          value="bot"
                        />
                        <strong>Bot</strong>
                        <span>Connect your strategy through the bot API.</span>
                      </label>
                    </div>
                  </fieldset>
                  <div className={styles.field}>
                    <label htmlFor="display-name">Table Display Name</label>
                    <input
                      autoComplete="nickname"
                      id="display-name"
                      maxLength={80}
                      name="displayName"
                      placeholder={kind === "human" ? "e.g. Maya…" : "e.g. RiverRunner…"}
                      required
                    />
                  </div>
                  {error && <p className={styles.formError}>{error}</p>}
                  <button className={styles.primaryButton} disabled={busy === "join"} type="submit">
                    {busy === "join" ? "Registering…" : `Register as ${kind === "human" ? "Human" : "Bot"}`}
                  </button>
                </form>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
