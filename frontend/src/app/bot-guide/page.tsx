import type { Metadata } from "next";
import Link from "next/link";

import styles from "@/features/account/account.module.css";

export const metadata: Metadata = {
  title: "Bot Protocol Guide | ACM Poker",
  description: "Build a poker bot: three HTTP endpoints, one JSON request per decision.",
};

const sampleRequest = `{
  "protocol": "poker-bot.v2",
  "match_id": "m-3f1c9a2b7d10",
  "table_id": "m-3f1c9a2b7d10-table",
  "hand_id": "m-3f1c9a2b7d10-table-hand-2",
  "decision_id": "6d1f0c8e-3e0b-4c8d-9a1e-2b5c7f9e1a33",
  "table_version": 3,
  "deadline_at": "2026-10-24T19:42:07.512Z",
  "table": {
    "street": "flop",
    "button_seat": 1,
    "blinds": { "small_blind": 100, "big_blind": 200, "big_blind_ante": 0 },
    "community_cards": ["2c", "7d", "Jh"],
    "seats": [
      { "seat": 1, "entrant_id": "e-bot", "display_name": "RiverRunner", "kind": "bot",
        "stack": 19800, "committed_this_street": 0, "committed_this_hand": 200,
        "folded": false, "all_in": false, "eliminated": false },
      { "seat": 2, "entrant_id": "e-human", "display_name": "Maya", "kind": "human",
        "stack": 19800, "committed_this_street": 0, "committed_this_hand": 200,
        "folded": false, "all_in": false, "eliminated": false }
    ],
    "pot": 400,
    "side_pots": [],
    "action_history": [
      { "sequence": 1, "seat": 1, "street": "preflop", "action": "call",
        "amount_to": null, "automatic": false },
      { "sequence": 2, "seat": 2, "street": "preflop", "action": "check",
        "amount_to": null, "automatic": false }
    ]
  },
  "player": { "seat": 1, "stack": 19800, "committed_this_street": 0,
              "hole_cards": ["As", "Kd"] },
  "legal_actions": [
    { "action": "check", "amount": null, "min_amount_to": null, "max_amount_to": null },
    { "action": "raise", "amount": null, "min_amount_to": 200, "max_amount_to": 19800 }
  ],
  "match": { "hand_number": 2, "level_number": 1, "players_remaining": 2,
             "seconds_until_next_level": null,
             "next_small_blind": null, "next_big_blind": null },
  "previous_hand": {
    "hand_id": "m-3f1c9a2b7d10-table-hand-1", "hand_number": 1,
    "community_cards": ["Qs", "Td", "4c", "4h", "9s"],
    "shown_hands": [{ "seat": 1, "hole_cards": ["Qh", "Jc"] },
                    { "seat": 2, "hole_cards": ["8d", "8c"] }],
    "awards": [{ "seat": 1, "amount": 800 }],
    "final_stacks": [{ "seat": 1, "entrant_id": "e-bot", "stack": 20400 },
                     { "seat": 2, "entrant_id": "e-human", "stack": 19600 }]
  }
}`;

const sampleResponse = `{
  "protocol": "poker-bot.v2",
  "match_id": "m-3f1c9a2b7d10",
  "table_id": "m-3f1c9a2b7d10-table",
  "hand_id": "m-3f1c9a2b7d10-table-hand-2",
  "decision_id": "6d1f0c8e-3e0b-4c8d-9a1e-2b5c7f9e1a33",
  "table_version": 3,
  "action": "raise",
  "amount_to": 600
}`;

const failures: [string, string][] = [
  ["timeout", "No complete answer within 3 seconds (500 ms to connect)."],
  ["connection", "Wrong IP or port, bot not running, or a firewall blocking the port."],
  ["http_status", "A non-2xx status. 401 usually means a stale token."],
  ["content_type", "Missing Content-Type: application/json."],
  ["malformed_json", "Invalid JSON, or a key appears twice."],
  ["schema", "Wrong protocol string, extra or misspelled field, or a string where an integer belongs."],
  ["stale", "An echoed identifier does not match the request."],
  ["illegal_action", "Action not offered, or a raise outside min/max."],
];

export default function BotGuidePage() {
  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Bot Protocol · v2</span>
        <Link className={styles.textButton} href="/dashboard#bots">My Bots</Link>
      </header>
      <div className={styles.dashboard}>
        <section className={styles.dashboardIntro}>
          <div>
            <p className={styles.eyebrow}>Builder quickstart</p>
            <h1>Host three<br /><em>endpoints.</em></h1>
          </div>
          <p>
            Your bot runs on your own laptop on the event Wi-Fi. When it is your bot&apos;s turn, the
            platform sends one JSON request; your bot answers with one legal action.
          </p>
        </section>
        <div className={styles.workspace}>
          <aside className={styles.sidebar}>
            <section className={styles.sidebarCard}>
              <h2>Four steps</h2>
              <ol className={styles.protocolList}>
                <li>Start a starter bot from <code>examples/bots/</code> on port 8001.</li>
                <li>Under <Link href="/dashboard#bots">My Bots</Link>, add it with your laptop&apos;s LAN IP, not localhost.</li>
                <li>Paste the one-time token into the bot as <code>BOT_TOKEN</code>, restart it, and press <strong>Verify</strong>.</li>
                <li>Enter the organizer&apos;s match code and choose <strong>My bot</strong>. The same bot can join every match.</li>
              </ol>
            </section>
            <section className={styles.sidebarCard}>
              <h2>Check before the event</h2>
              <pre className={styles.codeSample}><code>{`python -m poker_bot_platform.bots.conformance \\
  --ip 192.168.1.42 --port 8001 \\
  --token YOUR_TOKEN \\
  --participant-subnet 192.168.0.0/16`}</code></pre>
            </section>
          </aside>
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <div>
                <p className={styles.sectionLabel}>Required interface</p>
                <h2>Protocol surface</h2>
                <p className={styles.panelIntro}>POST routes carry <code>Authorization: Bearer &lt;token&gt;</code>.</p>
              </div>
              <span className={styles.statusPill}>poker-bot.v2</span>
            </div>
            <div className={styles.adminBody}>
              <div className={styles.entrantSummary}>
                <div><span className={styles.sectionLabel}>Health · no auth</span><h3><code>GET /v1/health</code></h3></div>
                <span>{`{"protocol":"poker-bot.v2","status":"ready"}`}</span>
              </div>
              <div className={styles.entrantSummary}>
                <div><span className={styles.sectionLabel}>Verification</span><h3><code>POST /v1/verify</code></h3></div>
                <span>Echo the challenge</span>
              </div>
              <div className={styles.entrantSummary}>
                <div><span className={styles.sectionLabel}>Decisions</span><h3><code>POST /v1/action</code></h3></div>
                <span>Return one action</span>
              </div>
              <section className={styles.protocolSection}>
                <div>
                  <h3>A complete request</h3>
                  <p className={styles.panelIntro}>
                    Your own hole cards, the public table, every action this hand with its street,
                    the legal actions, match context, and a public summary of the previous hand.
                    Other players&apos; unshown cards are never sent.
                  </p>
                </div>
                <pre className={styles.codeSample}><code>{sampleRequest}</code></pre>
              </section>
              <section className={styles.protocolSection}>
                <div>
                  <h3>The response</h3>
                  <p className={styles.panelIntro}>
                    Echo the five identifiers exactly. <code>amount_to</code> appears only with
                    <code> raise</code> and is your <strong>total for this street</strong>, not the extra
                    chips. To bet 600 on a fresh flop, send 600.
                  </p>
                </div>
                <pre className={styles.codeSample}><code>{sampleResponse}</code></pre>
              </section>
              <section className={styles.protocolSection}>
                <div>
                  <h3>When something goes wrong</h3>
                  <p className={styles.panelIntro}>
                    The table never waits on a broken bot: it checks when possible, otherwise folds,
                    and records why. Your recent decisions and these reasons appear under
                    <strong> My Bots → Diagnostics</strong>. After three connection failures in a
                    row, the platform probes <code>/v1/health</code> briefly before each decision
                    instead of waiting the full three seconds.
                  </p>
                </div>
                <ul className={styles.protocolList}>
                  {failures.map(([reason, copy]) => (
                    <li key={reason}><code>{reason}</code>: {copy}</li>
                  ))}
                </ul>
              </section>
              <section className={styles.protocolSection}>
                <div><h3>Common mistakes</h3></div>
                <ul className={styles.protocolList}>
                  <li>Registering <code>127.0.0.1</code>: the platform runs on another machine.</li>
                  <li>Sending <code>amount_to</code> as the extra chips instead of the street total.</li>
                  <li>Sending a number in <code>amount_to</code> with <code>check</code> or <code>call</code>.</li>
                  <li>Still answering with <code>poker-bot.v1</code>.</li>
                  <li>Forgetting to verify again after changing the address or rotating the token.</li>
                </ul>
              </section>
              <p className={styles.panelIntro}>
                Starter bots in Python and JavaScript live in <code>examples/bots/</code>; the JSON
                Schemas generated from the platform&apos;s models live in <code>schemas/</code>.
              </p>
              <div className={styles.panelActions}>
                <Link className={styles.primaryButton} href="/dashboard#bots">Add My Bot →</Link>
                <Link className={styles.secondaryButton} href="/demo">Watch Bots Play</Link>
              </div>
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
