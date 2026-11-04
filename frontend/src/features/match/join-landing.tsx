import Link from "next/link";

import { CodeEntry } from "./join-match";
import styles from "./join-landing.module.css";

export function JoinLanding() {
  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link href="/">ACM / POKER</Link>
        <Link href="/dashboard">Dashboard</Link>
      </header>
      <section className={styles.content}>
        <div className={styles.intro}>
          <p>Join a match</p>
          <h1>Take your seat.</h1>
          <p>
            Enter the six-character code from the organizer. You will sign in or create an
            account next, then choose to play yourself or seat one of your bots.
          </p>
        </div>
        <div className={styles.panel}>
          <CodeEntry />
          <span className={styles.or}>or practice first</span>
          <Link className={styles.demoLink} href="/demo">
            <span>Real engine, no account</span>
            <strong>Play three test bots</strong>
            <b>↗</b>
          </Link>
          <Link className={styles.demoLink} href="/play/demo">
            <span>Learn the controls</span>
            <strong>Open a table preview</strong>
            <b>↗</b>
          </Link>
        </div>
      </section>
      <footer className={styles.footer}>
        <span>No real money</span><span>Up to six players</span><span>Humans and bots</span>
      </footer>
    </main>
  );
}
