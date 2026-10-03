"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import styles from "./play.module.css";

export function JoinTable() {
  const router = useRouter();
  const [tournamentId, setTournamentId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const join = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = tournamentId.trim();
    if (!normalized) {
      setError("Enter the tournament ID supplied by the organizer.");
      return;
    }
    setError(null);
    router.push(`/play/${encodeURIComponent(normalized)}`);
  };

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link href="/">ACM / POKER</Link>
        <Link href="/account">Account / Sign In</Link>
      </header>
      <section className={styles.content}>
        <div className={styles.intro}>
          <p>Player table</p>
          <h1>Take your seat.</h1>
          <p>
            Enter the tournament ID supplied by the organizer. Your account must already be
            registered and seated as a human entrant.
          </p>
        </div>
        <div className={styles.panel}>
          <form onSubmit={join}>
            <label htmlFor="tournament-id">Tournament ID</label>
            <div>
              <input
                autoComplete="off"
                aria-describedby={error ? "tournament-id-error" : undefined}
                aria-invalid={Boolean(error)}
                id="tournament-id"
                name="tournamentId"
                onChange={(event) => {
                  setTournamentId(event.target.value);
                  if (error) setError(null);
                }}
                placeholder="e.g. club-event…"
                spellCheck={false}
                value={tournamentId}
              />
              <button type="submit">Join Table →</button>
            </div>
            {error && (
              <p className={styles.fieldError} id="tournament-id-error" role="alert">
                {error}
              </p>
            )}
          </form>
          <span className={styles.or}>or</span>
          <Link className={styles.demoLink} href="/play/demo">
            <span>Explore the interface</span>
            <strong>Open a safe demo table</strong>
            <b>↗</b>
          </Link>
        </div>
      </section>
      <footer className={styles.footer}>
        <span>No real money</span><span>Six-player tables</span><span>Server-authoritative play</span>
      </footer>
    </main>
  );
}
