import Link from "next/link";

import styles from "@/features/account/account.module.css";

export default function BotGuidePage() {
  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Bot Protocol · v1</span>
        <Link className={styles.textButton} href="/dashboard">My Entry</Link>
      </header>
      <div className={styles.dashboard}>
        <section className={styles.dashboardIntro}>
          <div>
            <p className={styles.eyebrow}>Builder Quickstart</p>
            <h1>Host three<br /><em>endpoints.</em></h1>
          </div>
          <p>
            Your bot runs on your own laptop and listens on the event Wi-Fi. The platform sends
            authenticated JSON requests; your service returns one legal poker action.
          </p>
        </section>
        <div className={styles.workspace}>
          <aside className={styles.sidebar}>
            <section className={styles.sidebarCard}>
              <h2>Before Event Day</h2>
              <p>Run your bot, save the one-time token, configure its LAN address, then verify it from your dashboard.</p>
            </section>
          </aside>
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <div>
                <p className={styles.sectionLabel}>Required Interface</p>
                <h2>Protocol Surface</h2>
                <p className={styles.panelIntro}>All routes use the bearer token shown during endpoint setup.</p>
              </div>
              <span className={styles.statusPill}>poker-bot.v1</span>
            </div>
            <div className={styles.adminBody}>
              <div className={styles.entrantSummary}>
                <div><span className={styles.sectionLabel}>Health</span><h3><code>GET /v1/health</code></h3></div>
                <span>Reachability</span>
              </div>
              <div className={styles.entrantSummary}>
                <div><span className={styles.sectionLabel}>Verification</span><h3><code>POST /v1/verify</code></h3></div>
                <span>Echo Challenge</span>
              </div>
              <div className={styles.entrantSummary}>
                <div><span className={styles.sectionLabel}>Decisions</span><h3><code>POST /v1/action</code></h3></div>
                <span>Return Action</span>
              </div>
              <section className={styles.protocolSection}>
                <div>
                  <h3>Decision response</h3>
                  <p className={styles.panelIntro}>
                    Echo every identifier and version exactly. For a raise, <code>amount_to</code>
                    is the player&apos;s total chips committed on the current street.
                  </p>
                </div>
                <pre className={styles.codeSample}><code>{`{
  "protocol": "poker-bot.v1",
  "tournament_id": "club-event",
  "table_id": "club-event-table-1",
  "hand_id": "club-event-table-1-hand-1",
  "decision_id": "decision-id-from-request",
  "table_version": 12,
  "action": "check",
  "amount_to": null
}`}</code></pre>
              </section>
              <section className={styles.protocolSection}>
                <div>
                  <h3>What the request contains</h3>
                  <p className={styles.panelIntro}>
                    The action request includes the deadline, public table state, every seat and
                    stack, community cards, action history, your private hole cards, and the exact
                    legal actions. Other players&apos; private cards are never included.
                  </p>
                </div>
                <ul className={styles.protocolList}>
                  <li>Authenticate every POST with <code>Authorization: Bearer &lt;token&gt;</code>.</li>
                  <li>Return JSON with <code>Content-Type: application/json</code> before the deadline.</li>
                  <li>Use JSON integers for chip counts and versions, never numeric strings.</li>
                  <li>Do not add unknown fields; the v1 schemas reject them.</li>
                </ul>
              </section>
              <section className={styles.protocolSection}>
                <div>
                  <h3>Failure behavior</h3>
                  <p className={styles.panelIntro}>
                    A timeout, connection error, non-2xx status, wrong content type, oversized or
                    malformed JSON, invalid schema, stale response, or illegal action triggers a
                    deterministic check-or-fold fallback. The hand continues and the reason appears
                    in the table action history.
                  </p>
                </div>
              </section>
              <p className={styles.panelIntro}>
                Starter bots and the conformance runner live in <code>examples/bots/</code>. The
                versioned request and response schemas live in <code>schemas/</code>.
              </p>
              <div className={styles.panelActions}>
                <Link className={styles.primaryButton} href="/dashboard">Configure My Bot →</Link>
                <Link className={styles.secondaryButton} href="/play/demo">See the Table Demo</Link>
              </div>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
