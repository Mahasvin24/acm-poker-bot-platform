"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";

import {
  AccountApiError,
  createTournament,
  getAdminTournament,
  getMe,
  logoutAccount,
  runAdminCommand,
  updateTournament,
} from "./api";
import styles from "./account.module.css";
import type { Account, AdminTournamentState, TournamentConfig } from "./types";

interface AdminDashboardProps {
  initialTournamentId: string;
}

function statusLabel(status: string): string {
  return status
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function AdminDashboard({ initialTournamentId }: AdminDashboardProps) {
  const router = useRouter();
  const [account, setAccount] = useState<Account | null>(null);
  const [tournamentId, setTournamentId] = useState(initialTournamentId);
  const [activeTournamentId, setActiveTournamentId] = useState(initialTournamentId);
  const [tournament, setTournament] = useState<AdminTournamentState | null>(null);
  const [lookupComplete, setLookupComplete] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inviteInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const current = await getMe();
        if (!active) return;
        if (current.role !== "admin") {
          router.replace("/dashboard");
          return;
        }
        setAccount(current);
        if (initialTournamentId) {
          try {
            const currentTournament = await getAdminTournament(initialTournamentId);
            if (active) setTournament(currentTournament);
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
        setError("The admin service is unavailable. Check that the API is running.");
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, [initialTournamentId, router]);

  const refresh = async (id = activeTournamentId) => {
    const next = await getAdminTournament(id);
    setTournament(next);
    return next;
  };

  const findTournament = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = tournamentId.trim();
    if (!normalized) {
      setError("Enter a tournament ID.");
      return;
    }
    setBusy("lookup");
    setError(null);
    setNotice(null);
    try {
      const found = await getAdminTournament(normalized);
      setTournament(found);
    } catch (requestError) {
      if (requestError instanceof AccountApiError && requestError.status === 404) {
        setTournament(null);
        setNotice("No tournament uses that ID. You can create it with the default preset.");
      } else {
        setError(requestError instanceof Error ? requestError.message : "Tournament lookup failed.");
      }
    } finally {
      setActiveTournamentId(normalized);
      setLookupComplete(true);
      router.replace(`/admin?tournament=${encodeURIComponent(normalized)}`);
      setBusy(null);
    }
  };

  const create = async () => {
    setBusy("create");
    setError(null);
    setNotice(null);
    try {
      await createTournament(activeTournamentId);
      await refresh(activeTournamentId);
      setNotice("Draft tournament created with the default preset.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Tournament creation failed.");
    } finally {
      setBusy(null);
    }
  };

  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!tournament) return;
    const form = new FormData(event.currentTarget);
    const levelSeconds = Number(form.get("levelMinutes")) * 60;
    const config: TournamentConfig = {
      ...tournament.config,
      max_players: Number(form.get("maxPlayers")),
      starting_stack: Number(form.get("startingStack")),
      human_action_timeout_ms: Number(form.get("humanActionSeconds")) * 1000,
      break_every_levels: Number(form.get("breakEveryLevels")),
      break_duration_seconds: Number(form.get("breakMinutes")) * 60,
      levels: tournament.config.levels.map((level) => ({
        ...level,
        duration_seconds: levelSeconds,
      })),
    };
    setBusy("settings");
    setError(null);
    setNotice(null);
    try {
      await updateTournament(activeTournamentId, config);
      await refresh();
      setNotice("Tournament settings saved.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Settings update failed.");
    } finally {
      setBusy(null);
    }
  };

  const command = async (
    action: "open" | "seat" | "start" | "pause" | "resume" | "advance",
    copy: string,
  ) => {
    setBusy(action);
    setError(null);
    setNotice(null);
    try {
      await runAdminCommand(activeTournamentId, action);
      await refresh();
      setNotice(copy);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Tournament command failed.");
    } finally {
      setBusy(null);
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

  const invitePath = activeTournamentId
    ? `/account?tournament=${encodeURIComponent(activeTournamentId)}`
    : "/account";

  useEffect(() => {
    if (inviteInputRef.current) {
      inviteInputRef.current.value = new URL(invitePath, window.location.origin).toString();
    }
  }, [account, invitePath, tournament?.status]);

  const copyInvite = async () => {
    setError(null);
    setNotice(null);
    try {
      if (!navigator.clipboard) throw new Error("Clipboard access is unavailable");
      await navigator.clipboard.writeText(new URL(invitePath, window.location.origin).toString());
      setNotice("Participant invite link copied.");
    } catch {
      setError("Could not copy automatically. Select the invite link and copy it manually.");
    }
  };

  if (!account) {
    return (
      <main className={styles.page} id="main-content">
        <div className={styles.loading}><span>{error ?? "Loading Admin Account"}</span></div>
      </main>
    );
  }

  const draft = tournament?.status === "draft";

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Tournament Director</span>
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
            <p className={styles.eyebrow}>Admin Console</p>
            <h1>Run the<br /><em>room.</em></h1>
          </div>
          <p>
            Create the event, open registration, seat verified entrants, and control the live
            tournament. Every accepted command is recorded by the backend.
          </p>
        </section>

        <div className={styles.workspace}>
          <aside className={styles.sidebar}>
            <section className={styles.sidebarCard}>
              <h2>Open Tournament</h2>
              <p>Load an existing event or choose an unused ID for a new draft.</p>
              <form className={styles.form} onSubmit={findTournament}>
                <div className={styles.field}>
                  <label htmlFor="admin-tournament">Tournament ID</label>
                  <input
                    autoComplete="off"
                    id="admin-tournament"
                    name="tournamentId"
                    onChange={(event) => setTournamentId(event.target.value)}
                    placeholder="e.g. club-event…"
                    spellCheck={false}
                    value={tournamentId}
                  />
                </div>
                <button className={styles.secondaryButton} disabled={busy === "lookup"} type="submit">
                  {busy === "lookup" ? "Loading…" : "Load Tournament"}
                </button>
              </form>
            </section>
            <section className={styles.sidebarCard}>
              <h2>Event Safety</h2>
              <p>Seat and level changes occur through serialized, audited backend commands.</p>
            </section>
          </aside>

          <section aria-live="polite">
            {!lookupComplete ? (
              <div className={styles.emptyState}>
                <p className={styles.sectionLabel}>No Tournament Selected</p>
                <h2>Load an event to begin.</h2>
                <p>The default preset is applied when you create a new tournament.</p>
              </div>
            ) : !tournament ? (
              <div className={styles.emptyState}>
                <p className={styles.sectionLabel}>{activeTournamentId}</p>
                <h2>Create this tournament?</h2>
                <p>It will begin as a draft with the configured 20,000-chip default preset.</p>
                {notice && <p className={styles.successMessage}>{notice}</p>}
                {error && <p className={styles.formError}>{error}</p>}
                <div className={styles.panelActions}>
                  <button className={styles.primaryButton} disabled={busy === "create"} onClick={create} type="button">
                    {busy === "create" ? "Creating…" : "Create Draft Tournament"}
                  </button>
                </div>
              </div>
            ) : (
              <div className={styles.panel}>
                <div className={styles.panelHead}>
                  <div>
                    <p className={styles.sectionLabel}>{tournament.tournament_id}</p>
                    <h2>{statusLabel(tournament.status)}</h2>
                    <p className={styles.panelIntro}>Revision {tournament.revision}</p>
                  </div>
                  <span className={styles.statusPill} data-status={tournament.status}>
                    {tournament.status === "running"
                      ? `Level ${tournament.level_number} · ${formatDuration(tournament.phase_remaining_seconds)}`
                      : statusLabel(tournament.status)}
                  </span>
                </div>

                <div className={styles.stats}>
                  <div className={styles.stat}><span>Entrants</span><strong>{tournament.entrant_count}</strong></div>
                  <div className={styles.stat}><span>Humans</span><strong>{tournament.human_count}</strong></div>
                  <div className={styles.stat}><span>Bots Ready</span><strong>{tournament.verified_bot_count}/{tournament.bot_count}</strong></div>
                  <div className={styles.stat}><span>Tables</span><strong>{tournament.table_count}</strong></div>
                </div>

                <div className={styles.adminBody}>
                  {tournament.status !== "draft" && (
                    <section className={styles.inviteCard} aria-labelledby="invite-heading">
                      <div>
                        <h3 id="invite-heading">Participant Invite</h3>
                        <p className={styles.panelIntro}>
                          Share this link with human players and bot builders. It carries the
                          tournament ID through account creation and sign-in.
                        </p>
                      </div>
                      <div className={styles.inviteControls}>
                        <input
                          aria-label="Participant invite link"
                          defaultValue={invitePath}
                          onFocus={(event) => event.currentTarget.select()}
                          readOnly
                          ref={inviteInputRef}
                        />
                        <button className={styles.copyButton} onClick={copyInvite} type="button">
                          Copy Invite
                        </button>
                      </div>
                    </section>
                  )}

                  <form className={styles.settings} onSubmit={saveSettings}>
                    <div>
                      <h3>Tournament Settings</h3>
                      <p className={styles.panelIntro}>Editable only while this event is a draft.</p>
                    </div>
                    <div className={styles.settingsGrid}>
                      <div className={styles.field}>
                        <label htmlFor="max-players">Maximum Players</label>
                        <input defaultValue={tournament.config.max_players} disabled={!draft} id="max-players" max={36} min={2} name="maxPlayers" required type="number" />
                      </div>
                      <div className={styles.field}>
                        <label htmlFor="starting-stack">Starting Chips</label>
                        <input defaultValue={tournament.config.starting_stack} disabled={!draft} id="starting-stack" min={1} name="startingStack" required type="number" />
                      </div>
                      <div className={styles.field}>
                        <label htmlFor="human-timeout">Human Clock (Seconds)</label>
                        <input defaultValue={tournament.config.human_action_timeout_ms / 1000} disabled={!draft} id="human-timeout" min={1} name="humanActionSeconds" required type="number" />
                      </div>
                      <div className={styles.field}>
                        <label htmlFor="level-minutes">Level Length (Minutes)</label>
                        <input defaultValue={tournament.config.levels[0]?.duration_seconds / 60} disabled={!draft} id="level-minutes" min={1} name="levelMinutes" required type="number" />
                      </div>
                      <div className={styles.field}>
                        <label htmlFor="break-every">Break Every N Levels</label>
                        <input defaultValue={tournament.config.break_every_levels} disabled={!draft} id="break-every" min={1} name="breakEveryLevels" required type="number" />
                      </div>
                      <div className={styles.field}>
                        <label htmlFor="break-minutes">Break Length (Minutes)</label>
                        <input defaultValue={tournament.config.break_duration_seconds / 60} disabled={!draft} id="break-minutes" min={0} name="breakMinutes" required type="number" />
                      </div>
                    </div>
                    {draft && (
                      <button className={styles.secondaryButton} disabled={busy === "settings"} type="submit">
                        {busy === "settings" ? "Saving…" : "Save Draft Settings"}
                      </button>
                    )}
                  </form>

                  <div className={styles.commands}>
                    <div>
                      <h3>Tournament Commands</h3>
                      <p className={styles.panelIntro}>Only commands valid for the current state are available.</p>
                    </div>
                    <div className={styles.commandsGrid}>
                      {tournament.status === "draft" && (
                        <button className={styles.primaryButton} disabled={Boolean(busy)} onClick={() => command("open", "Registration is now open.")} type="button">Open Registration</button>
                      )}
                      {tournament.status === "registration_open" && (
                        <button className={styles.primaryButton} disabled={Boolean(busy)} onClick={() => command("seat", "Entrants seated.")} type="button">Seat Entrants</button>
                      )}
                      {tournament.status === "seated" && (
                        <button className={styles.dangerButton} disabled={Boolean(busy)} onClick={() => command("start", "Tournament started.")} type="button">Start Tournament</button>
                      )}
                      {tournament.status === "running" && (
                        <>
                          <button className={styles.secondaryButton} disabled={Boolean(busy)} onClick={() => command("pause", "Pause requested after active hands finish.")} type="button">Pause After Hands</button>
                          <button className={styles.commandButton} disabled={Boolean(busy)} onClick={() => command("advance", "Level advanced.")} type="button">Advance Level</button>
                        </>
                      )}
                      {tournament.status === "paused" && (
                        <button className={styles.primaryButton} disabled={Boolean(busy)} onClick={() => command("resume", "Tournament resumed.")} type="button">Resume Tournament</button>
                      )}
                      <button className={styles.commandButton} disabled={Boolean(busy)} onClick={() => refresh().catch((requestError: unknown) => setError(requestError instanceof Error ? requestError.message : "Refresh failed."))} type="button">Refresh State</button>
                    </div>
                  </div>
                  {notice && <p className={styles.successMessage}>{notice}</p>}
                  {error && <p className={styles.formError}>{error}</p>}
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
