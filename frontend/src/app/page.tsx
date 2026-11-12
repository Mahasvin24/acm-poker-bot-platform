import Image from "next/image";
import Link from "next/link";

import { MotionController } from "./motion-controller";
import { MobileMenu } from "./mobile-menu";

const tickerItems = [
  "No-limit Hold’em",
  "Six-player tables",
  "Play-money",
  "Humans and bots",
];

const timeline = [
  {
    number: "01",
    title: "Make an account",
    copy: "Sign up as a human to play, or as a bot to connect your code.",
    timing: "Any time",
  },
  {
    number: "02",
    title: "Test your bot",
    copy: "Bot builders save their connection settings and test their bot on the dashboard.",
    timing: "Bots only",
  },
  {
    number: "03",
    title: "Take your seat",
    copy: "Enter the six-character code from the organizer.",
    timing: "Event day",
  },
  {
    number: "04",
    title: "Play the match",
    copy: "Play until the time or hand limit, or until one player remains. Remaining stacks determine the standings.",
    timing: "Live",
    live: true,
  },
];

const questions = [
  {
    question: "Do I need to know how to code?",
    answer:
      "No. Human entrants play through a normal poker interface. Coding is only needed to enter a bot.",
  },
  {
    question: "What does my bot need?",
    answer:
      "A small HTTP API running on your laptop and connected to the same event Wi-Fi.",
  },
  {
    question: "Is there real money involved?",
    answer: "No. This is a friendly, play-money ACM club event.",
  },
  {
    question: "What if my bot misses a turn?",
    answer:
      "The table keeps moving. It checks when possible and otherwise folds.",
  },
];

export default function Home() {
  return (
    <>
      <MotionController />
      <div className="progress" aria-hidden="true">
        <span />
      </div>

      <header className="site-header">
        <div className="container site-header__inner">
          <a
            className="brand"
            href="#welcome"
            aria-label="ACM Poker home"
          >
            <Image
              className="logo"
              src="/acm-logo.png"
              alt="ACM logo"
              width={58}
              height={58}
              priority
            />
            <span className="brand-copy">
              <strong>ACM POKER</strong>
              <span>HUMAN × MACHINE</span>
            </span>
          </a>
          <nav className="site-nav" aria-label="Primary navigation">
            <a href="#format">Format</a>
            <a href="#timeline">Timeline</a>
            <a href="#faq">FAQ</a>
            <Link href="/join">Join a Match</Link>
            <Link className="nav-pill" href="/account">
              <i aria-hidden="true" /> Sign In / Register
            </Link>
          </nav>
          <MobileMenu />
        </div>
      </header>

      <main id="main-content">
        <section className="page-section hero" id="welcome">
          <div className="deal-scene" aria-hidden="true">
            <div className="table-plane">
              <span className="dealer-button">D</span>
            </div>
            <div className="deck-stack">
              <span />
              <span />
              <span />
            </div>
            <div className="dealt-card dealt-card--one">
              <span>A</span>
              <b>♠</b>
            </div>
            <div className="dealt-card dealt-card--two">
              <span>K</span>
              <b>♥</b>
            </div>
          </div>

          <div className="container hero-inner">
            <p className="eyebrow reveal">
              ACM presents · No-limit Hold’em · Play money
            </p>
            <h1 aria-label="One table. Any mind.">
              <span className="title-line">
                <span>One table.</span>
              </span>
              <span className="title-line title-line--accent">
                <span>Any mind.</span>
              </span>
            </h1>
            <div className="hero-bottom reveal">
              <p>
                Play no-limit Hold’em against people and student-built bots. Enter the organizer’s code to join.
              </p>
              <Link className="round-link" href="/join">
                <span>Join a match</span>
                <b>→</b>
              </Link>
            </div>
          </div>
          <p className="side-note side-note--left">
            Up to 6 per table
          </p>
          <p className="side-note side-note--right">Scroll to deal</p>
        </section>

        <section className="page-section format" id="format">
          <div className="container format-inner">
            <div className="format-head reveal">
              <h2>
                Same table.
                <br />
                Different interface.
              </h2>
            </div>

            <div className="duel reveal">
              <article className="player player--human">
                <div className="player-meta">
                  <span>01</span>
                  <span>Human</span>
                </div>
                <div>
                  <p className="player-mark">H</p>
                  <h3>Play in your browser</h3>
                  <p>
                    See your cards, follow the action, and choose your next move.
                  </p>
                </div>
                <span className="player-tag">No code required</span>
              </article>
              <div className="duel-center" aria-hidden="true">
                <span>VS</span>
              </div>
              <article className="player player--bot">
                <div className="player-meta">
                  <span>02</span>
                  <span>Bot</span>
                </div>
                <div>
                  <p className="player-mark">B</p>
                  <h3>Enter your bot</h3>
                  <p>
                    Connect your own strategy over the event network. We send
                    the hand; your API returns the move.
                  </p>
                </div>
                <span className="player-tag">Bring an HTTP API</span>
              </article>
            </div>

            <div className="ticker" aria-label="Format">
              <div>
                {tickerItems.map((item) => (
                  <span className="ticker-item" key={item}>
                    <span>{item}</span>
                    <i aria-hidden="true">◆</i>
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="page-section timeline" id="timeline">
          <div className="container timeline-inner">
            <div className="timeline-title reveal">
              <h2>
                How to join
              </h2>
            </div>
            <ol className="timeline-list">
              {timeline.map((item) => (
                <li className="reveal" key={item.number}>
                  <span className="step">{item.number}</span>
                  <div>
                    <h3>{item.title}</h3>
                    <p>{item.copy}</p>
                  </div>
                  <span className={item.live ? "when when--live" : "when"}>
                    {item.live && <i aria-hidden="true" />}
                    {item.timing}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="page-section faq" id="faq">
          <div className="faq-watermark" aria-hidden="true">
            ?
          </div>
          <div className="container faq-inner">
            <div className="faq-intro reveal">
              <h2>
                Questions
              </h2>
              <p>
                Build a bot with the{" "}
                <Link href="/bot-guide">endpoint guide</Link>, or head straight
                to your{" "}
                <Link href="/dashboard">dashboard</Link>.
              </p>
            </div>
            <div className="questions reveal">
              {questions.map((item, index) => (
                <details key={item.question} open={index === 0}>
                  <summary>
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    {item.question}
                    <b />
                  </summary>
                  <p>{item.answer}</p>
                </details>
              ))}
            </div>
          </div>
          <footer className="container footer reveal">
            <span>ACM · Poker: Humans vs. Bots</span>
            <span>Dates and location coming soon</span>
            <a href="#welcome">Back to top ↑</a>
          </footer>
        </section>
      </main>
    </>
  );
}
