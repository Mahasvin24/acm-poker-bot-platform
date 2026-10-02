"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import styles from "./play.module.css";

export function JoinTable() {
  const router = useRouter();
  const [tournamentId, setTournamentId] = useState("");

  const join = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = tournamentId.trim();
    if (!normalized) return;
    router.push(`/play/${encodeURIComponent(normalized)}`);
  };

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Link href="/">ACM / POKER</Link>
        <span>Human player interface</span>
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
                id="tournament-id"
                onChange={(event) => setTournamentId(event.target.value)}
                placeholder="club-event"
                value={tournamentId}
              />
              <button disabled={!tournamentId.trim()} type="submit">Join table →</button>
            </div>
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
