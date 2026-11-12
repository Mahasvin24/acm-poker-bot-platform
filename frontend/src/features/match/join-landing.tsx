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
          <h1>Join a match</h1>
          <p>
            Enter the organizer’s six-character code. Sign in to join as a player or with your saved bot.
          </p>
        </div>
        <div className={styles.panel}>
          <CodeEntry />
          <span className={styles.or}>or practice first</span>
          <Link className={styles.demoLink} href="/demo">
            <span>No account needed</span>
            <strong>Practice against bots</strong>
            <b>↗</b>
          </Link>
          <Link className={styles.demoLink} href="/play/demo">
            <span>Preview only</span>
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
