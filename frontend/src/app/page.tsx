import Image from "next/image";
import Link from "next/link";

import { MotionController } from "./motion-controller";

const tickerItems = [
  "No-limit Hold’em",
  "Six-player tables",
  "Play-money",
  "One champion",
];

const timeline = [
  {
    number: "01",
    title: "Pick your side",
    copy: "Register as a human player or a bot builder.",
    timing: "Registration",
  },
  {
    number: "02",
    title: "Run the check",
    copy: "Bots verify their connection and response format.",
    timing: "Before event",
  },
  {
    number: "03",
    title: "Take your seat",
    copy: "Join the event Wi-Fi and receive a table assignment.",
    timing: "Event day",
  },
  {
    number: "04",
    title: "Play it down",
    copy: "The field competes until one stack remains.",
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
    answer: "No. This is a friendly, play-money ACM club tournament.",
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
            aria-label="ACM Poker Bot Tournament home"
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
            <Link href="/dashboard">Play</Link>
            <Link className="nav-pill" href="/account">
              <i aria-hidden="true" /> Sign In / Register
            </Link>
          </nav>
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
              <span className="title-line reveal">
                <span>One table.</span>
              </span>
              <span className="title-line title-line--accent reveal">
                <span>Any mind.</span>
              </span>
            </h1>
            <div className="hero-bottom reveal">
              <p>
                A live poker tournament where people play their instincts and
                student-built bots play their code.
              </p>
              <a className="round-link" href="#format">
                <span>See the format</span>
                <b>↓</b>
              </a>
            </div>
          </div>
          <p className="side-note side-note--left">
            36 entrants · 6 per table
          </p>
          <p className="side-note side-note--right">Scroll to deal</p>
        </section>

        <section
          className="page-section thesis"
          aria-label="Tournament introduction"
        >
          <div className="suit-field" aria-hidden="true">
            <span>♣</span>
            <span>♦</span>
            <span>♠</span>
            <span>♥</span>
          </div>
          <div className="container thesis-inner">
            <p className="chapter reveal">01 · The idea</p>
            <p className="statement reveal">
              Poker has always been a game of incomplete information.
            </p>
            <p className="statement statement--shift reveal">
              Now the player across from you might be <em>an API.</em>
            </p>
            <div className="thesis-foot reveal">
              <span>Bring your poker face.</span>
              <span>Or bring your code.</span>
            </div>
          </div>
        </section>

        <section className="page-section format" id="format">
          <div className="container format-inner">
            <div className="format-head reveal">
              <p className="chapter">02 · Choose your seat</p>
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
                  <h3>Read the room.</h3>
                  <p>
                    Play each hand through a focused browser interface. Your
                    cards, legal moves, and clock—nothing more.
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
                  <h3>Read the state.</h3>
                  <p>
                    Connect your own strategy over the event network. We send
                    the hand; your API returns the move.
                  </p>
                </div>
                <span className="player-tag">Bring an HTTP API</span>
              </article>
            </div>

            <div className="ticker" aria-label="Tournament format">
              <div>
                {[...tickerItems, ...tickerItems].map((item, index) => (
                  <span className="ticker-item" key={`${item}-${index}`}>
                    <span>{item}</span>
                    <i>◆</i>
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="page-section timeline" id="timeline">
          <div className="container timeline-inner">
            <div className="timeline-title reveal">
              <p className="chapter">03 · From signup to showdown</p>
              <h2>
                Four moments.
                <br />
                <em>One night.</em>
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
                    {item.live && <i />}
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
              <p className="chapter">04 · Before you ask</p>
              <h2>
                The fine print,
                <br />
                <em>kept simple.</em>
              </h2>
              <p>
                Full rules, bot documentation, and event logistics will arrive
                when registration opens.
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
            <span>ACM · Poker Bot Tournament</span>
            <span>Dates and location coming soon</span>
            <a href="#welcome">Back to top ↑</a>
          </footer>
        </section>
      </main>
    </>
  );
}
