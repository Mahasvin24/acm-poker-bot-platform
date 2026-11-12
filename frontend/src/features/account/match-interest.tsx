"use client";

import { useEffect, useState } from "react";

import { cancelLookingForMatch, getAdminMatch, invitePlayer, listAccounts, signalLookingForMatch } from "./api";
import styles from "./account.module.css";
import type { Account, AdminAccount, AdminMatch, AdminMatchSummary } from "./types";

const LOOKING_WINDOW_MS = 5 * 60 * 1000;

function isLooking(timestamp: string | null, now: number): boolean {
  if (!timestamp) return false;
  const elapsed = now - Date.parse(timestamp);
  return elapsed >= 0 && elapsed < LOOKING_WINDOW_MS;
}

function useCurrentTime() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, []);
  return now;
}

export function LookingForMatchCard({ account }: { account: Account }) {
  const [timestamp, setTimestamp] = useState(account.looking_for_match_at);
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const now = useCurrentTime();
  const looking = isLooking(timestamp, now);

  const signal = async (cancel = false) => {
    setBusy(true);
    setError(null);
    try {
      setTimestamp((await (cancel ? cancelLookingForMatch() : signalLookingForMatch())).looking_for_match_at);
      setCancelled(cancel);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send your signal. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`${styles.sidebarCard} ${styles.matchInterest}`}>
      <h2>Looking for a match?</h2>
      <p>Let the organizer know you’re ready. Your signal lasts five minutes.</p>
      <div className={styles.interestActions}>
        <div className={styles.interestButtons}>
        <button className={styles.primaryButton} disabled={busy} onClick={() => void signal()} type="button">
          {busy ? "Sending…" : looking ? "Still looking — refresh" : "Looking for a match"}
        </button>
        {looking && <button aria-label="Cancel looking for a match" className={styles.textButton} disabled={busy} onClick={() => void signal(true)} type="button">Cancel</button>}
        </div>
        <p className={styles.interestStatus} role="status">
          {looking && <span aria-hidden="true" className={styles.lookingDot} />}
          {looking ? "You’re marked as looking for a match." : cancelled ? "You’re no longer looking for a match." : timestamp ? "Your signal expired. Click again if you’re still looking." : "Click when you’re ready to play."}
        </p>
      </div>
      {error && <p className={styles.formError} role="alert">{error}</p>}
    </section>
  );
}

export function PlayersPanel({ matches, matchId }: { matches?: AdminMatchSummary[] | null; matchId?: string }) {
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<AdminMatch | null>(null);
  const [inviting, setInviting] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const lobbies = matches?.filter((match) => match.status === "lobby") ?? [];
  const targetId = matchId ?? (lobbies.some((match) => match.match_id === selected) ? selected : lobbies[0]?.match_id ?? "");
  const [accounts, setAccounts] = useState<AdminAccount[] | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const now = useCurrentTime();

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const [rows, target] = await Promise.all([listAccounts(), targetId ? getAdminMatch(targetId) : Promise.resolve(null)]);
        if (active) {
          setAccounts(rows);
          setDetail(target);
          setError(null);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load players.");
      }
    };
    void load();
    const interval = window.setInterval(() => void load(), 3_000);
    return () => { active = false; window.clearInterval(interval); };
  }, [targetId]);

  const invite = async (player: AdminAccount) => {
    if (!targetId) return;
    setInviting(player.id);
    setError(null);
    setNotice(null);
    try {
      setDetail(await invitePlayer(targetId, player.id));
      setNotice(`Invited ${player.display_name ?? player.email}. They can accept or decline on their profile.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not send invitation.");
    } finally {
      setInviting(null);
    }
  };

  const players = accounts?.filter((item) => item.role === "user") ?? [];
  const lookingCount = players.filter((item) => isLooking(item.looking_for_match_at, now)).length;
  const query = filter.trim().toLowerCase();
  const shown = players
    .filter((item) => `${item.display_name ?? ""} ${item.email}`.toLowerCase().includes(query))
    .sort((a, b) => (b.looking_for_match_at ? Date.parse(b.looking_for_match_at) : 0) - (a.looking_for_match_at ? Date.parse(a.looking_for_match_at) : 0));

  return (
    <section className={styles.panel} aria-labelledby="players-heading">
      <div className={styles.panelHead}>
        <div>
          <p className={styles.sectionLabel}>Players</p>
          <h2 id="players-heading">Who’s ready?</h2>
          <p className={styles.panelIntro}>{players.length} players · {lookingCount} looking for a match. Most recent signals first.</p>
        </div>
      </div>
      <div className={`${styles.field} ${styles.playerFilter}`}>
        {matchId ? <p className={styles.fieldHint}>Invite players to {detail?.name ?? "this match"}. Invitations don’t reserve seats.</p> : <>
          <label htmlFor="invite-match">Invite to match</label>
          <select id="invite-match" onChange={(event) => { setSelected(event.target.value); setNotice(null); }} value={targetId} disabled={lobbies.length === 0}>
            {lobbies.length === 0 && <option value="">Create a match to invite players</option>}
            {lobbies.map((match) => <option key={match.match_id} value={match.match_id}>{match.name} · {match.seats_taken}/{match.max_seats} seats</option>)}
          </select>
          <p className={styles.fieldHint}>Choose a lobby, then invite a player. They decide whether to join.</p>
        </>}
      </div>
      {notice && <p className={styles.successMessage} role="status">{notice}</p>}
      <div className={`${styles.field} ${styles.playerFilter}`}>
        <label htmlFor="player-filter">Find a player</label>
        <input id="player-filter" onChange={(event) => setFilter(event.target.value)} placeholder="Name or email" value={filter} type="search" />
      </div>
      {error && <p className={styles.formError} role="alert">{error} {accounts && "Showing the last loaded players."}</p>}
      {accounts === null ? <p className={styles.panelIntro}>Loading players…</p> : shown.length === 0 ? (
        <p className={styles.panelIntro}>{players.length === 0 ? "No players have signed up yet." : "No players match your search."}</p>
      ) : (
        <ul className={styles.playerList}>
          {shown.map((player) => {
            const looking = isLooking(player.looking_for_match_at, now);
            const target = detail?.match_id === targetId ? detail : null;
            const invitation = target?.invitations?.find((item) => item.account_id === player.id);
            const joined = target?.entries.some((entry) => entry.account_email === player.email);
            const pending = invitation?.status === "pending";
            const full = target ? target.entries.length >= target.config.max_seats : false;
            return (
              <li key={player.id}>
                <div className={styles.playerIdentity}>
                  <strong>{looking && <span aria-hidden="true" className={styles.lookingDot} />}{player.display_name ?? player.email.split("@")[0]}</strong>
                  <small>{player.email} · {player.participant_kind === "bot" ? "Bot" : player.participant_kind === "human" ? "Human" : "Player"}</small>
                </div>
                <div className={styles.playerInterest} data-looking={looking}>
                  <span>{looking ? "Looking for a match" : "Not looking"}</span>
                  {player.looking_for_match_at && <time dateTime={player.looking_for_match_at}>Last signal: {new Date(player.looking_for_match_at).toLocaleString()}</time>}
                </div>
                <button
                  className={styles.secondaryButton}
                  disabled={!targetId || !target || target.status !== "lobby" || full || Boolean(inviting) || joined || pending}
                  onClick={() => void invite(player)}
                  type="button"
                >{inviting === player.id ? "Sending…" : joined ? "Joined" : pending ? "Invited" : invitation?.status === "declined" ? "Invite again" : "Invite"}</button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
