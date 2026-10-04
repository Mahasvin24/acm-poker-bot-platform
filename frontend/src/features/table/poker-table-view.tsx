"use client";

import Link from "next/link";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import styles from "./poker-table.module.css";
import type {
  ActionType,
  HandResult,
  LegalAction,
  PlayerSeat,
  PlayerTableState,
  PublicTurn,
} from "./types";

export type PresentationPhase =
  | "dealing-private"
  | "awaiting-human"
  | "awaiting-opponent"
  | "resolving-action"
  | "revealing-flop"
  | "revealing-turn"
  | "revealing-river"
  | "showdown"
  | "complete";

interface PokerTableViewProps {
  table: PlayerTableState;
  submitting: boolean;
  notice: string | null;
  error: string | null;
  connectionLabel: string;
  connectionTone?: "live" | "reconnecting" | "demo";
  embedded?: boolean;
  fullScreen?: boolean;
  showSidePots?: boolean;
  animateInitialDeal?: boolean;
  onSubmit: (action: ActionType, amountTo?: number) => void;
}

const handStages = [
  { key: "preflop", label: "Pre-flop", detail: "Blinds + private cards" },
  { key: "flop", label: "Flop", detail: "First 3 community cards" },
  { key: "turn", label: "Turn", detail: "4th community card" },
  { key: "river", label: "River", detail: "Final community card" },
  { key: "showdown", label: "Showdown", detail: "Reveal + winner" },
] as const;

type HandStage = (typeof handStages)[number]["key"];

const chips = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const blindDepth = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const suits: Record<string, string> = { c: "♣", d: "♦", h: "♥", s: "♠" };
const suitNames: Record<string, string> = {
  c: "clubs",
  d: "diamonds",
  h: "hearts",
  s: "spades",
};

const failureReasonLabels: Record<string, string> = {
  timeout: "Timed out",
  malformed_json: "Malformed JSON",
  schema: "Invalid response shape",
  connection: "Connection failed",
  http_status: "HTTP error",
  content_type: "Wrong content type",
  oversized: "Response too large",
  stale: "Stale decision",
  illegal_action: "Illegal action",
  restart_recovery: "Server restart recovery",
};

function formatChips(value: number): string {
  return chips.format(value);
}

function actionCopy(action: ActionType): string {
  return action.charAt(0).toUpperCase() + action.slice(1);
}

function actionNarrative(
  action: PlayerTableState["action_history"][number] | undefined,
  names: Map<number, string>,
): string | null {
  if (!action) return null;
  const name = names.get(action.seat) ?? `Seat ${action.seat}`;
  const automatic = action.automatic ? " automatically" : "";
  if (action.action === "fold") return `${name}${automatic} folded.`;
  if (action.action === "check") return `${name}${automatic} checked.`;
  if (action.action === "call") {
    return `${name}${automatic} called${action.amount_to === null ? "" : ` to ${formatChips(action.amount_to)}`}.`;
  }
  return `${name}${automatic} raised${action.amount_to === null ? "" : ` to ${formatChips(action.amount_to)}`}.`;
}

function automaticActionCopy(failureReason: string | null): string {
  if (!failureReason) return "automatic fallback";
  return `fallback: ${failureReasonLabels[failureReason] ?? failureReason.replaceAll("_", " ")}`;
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

function targetPhase(table: PlayerTableState): PresentationPhase {
  if (table.completed) return table.hand_result?.reason === "showdown" ? "showdown" : "complete";
  if (table.decision) return "awaiting-human";
  if (table.turn) return "awaiting-opponent";
  return "resolving-action";
}

function currentHandStage(phase: PresentationPhase, table: PlayerTableState): HandStage {
  if (table.completed || phase === "showdown" || phase === "complete") return "showdown";
  if (phase === "revealing-river") return "river";
  if (phase === "revealing-turn") return "turn";
  if (phase === "revealing-flop") return "flop";
  if (table.community_cards.length >= 5 || table.street === "river") return "river";
  if (table.community_cards.length >= 4 || table.street === "turn") return "turn";
  if (table.community_cards.length >= 3 || table.street === "flop") return "flop";
  return "preflop";
}

function useTablePresentation(table: PlayerTableState, animateInitialDeal: boolean) {
  const reducedMotion = useReducedMotion();
  const settledPhase = targetPhase(table);
  const seatSignature = table.seats.map((seat) => seat.seat).join(",");
  const dealSeatNumbers = useMemo(
    () => seatSignature.split(",").filter(Boolean).map(Number),
    [seatSignature],
  );
  const [phase, setPhase] = useState<PresentationPhase>(() =>
    animateInitialDeal && !table.completed ? "dealing-private" : targetPhase(table),
  );
  const [revealedBySeat, setRevealedBySeat] = useState<Record<number, number>>(() =>
    animateInitialDeal ? {} : Object.fromEntries(table.seats.map((seat) => [seat.seat, 2])),
  );
  const [boardCount, setBoardCount] = useState(() =>
    animateInitialDeal ? 0 : table.community_cards.length,
  );
  const handRef = useRef(table.hand_id);
  const initialDealAnimatedRef = useRef(false);
  const boardRef = useRef(boardCount);

  useEffect(() => {
    const newHand = handRef.current !== table.hand_id;
    handRef.current = table.hand_id;
    const shouldAnimate = newHand || (animateInitialDeal && !initialDealAnimatedRef.current);
    if (!shouldAnimate) return;
    if (table.completed || reducedMotion) {
      const timer = window.setTimeout(
        () => {
          initialDealAnimatedRef.current = true;
          setRevealedBySeat(Object.fromEntries(dealSeatNumbers.map((seat) => [seat, 2])));
        },
        0,
      );
      return () => window.clearTimeout(timer);
    }

    const ordered = [...dealSeatNumbers].sort(
      (left, right) =>
        ((left - table.button_seat + 6) % 6 || 6) -
        ((right - table.button_seat + 6) % 6 || 6),
    );
    const interval = Math.round(Math.min(300, 2000 / Math.max(1, ordered.length * 2)));
    const timers: number[] = [];
    timers.push(window.setTimeout(() => {
      initialDealAnimatedRef.current = true;
      setPhase("dealing-private");
      setRevealedBySeat({});
    }, 0));
    ordered.forEach((seat, seatIndex) => {
      for (let round = 0; round < 2; round += 1) {
        timers.push(
          window.setTimeout(() => {
            setRevealedBySeat((current) => ({ ...current, [seat]: round + 1 }));
          }, (round * ordered.length + seatIndex + 1) * interval),
        );
      }
    });
    timers.push(
      window.setTimeout(
        () => setPhase(settledPhase),
        ordered.length * 2 * interval + 100,
      ),
    );
    return () => timers.forEach(window.clearTimeout);
  }, [animateInitialDeal, dealSeatNumbers, reducedMotion, settledPhase, table.button_seat, table.completed, table.hand_id]);

  useEffect(() => {
    const target = table.community_cards.length;
    const previous = boardRef.current;
    if (target <= previous || reducedMotion) {
      boardRef.current = target;
      const timer = window.setTimeout(() => setBoardCount(target), 0);
      return () => window.clearTimeout(timer);
    }

    const timers: number[] = [];
    const reveal = (count: number, label: PresentationPhase, delay: number) => {
      timers.push(
        window.setTimeout(() => {
          setPhase(label);
          setBoardCount(count);
          boardRef.current = count;
        }, delay),
      );
    };
    let delay = 180;
    if (previous < 3 && target >= 3) {
      reveal(1, "revealing-flop", delay);
      reveal(2, "revealing-flop", delay + 140);
      reveal(3, "revealing-flop", delay + 280);
      delay += 560;
    }
    if (previous < 4 && target >= 4) {
      reveal(4, "revealing-turn", delay);
      delay += 420;
    }
    if (previous < 5 && target >= 5) {
      reveal(5, "revealing-river", delay);
      delay += 420;
    }
    timers.push(window.setTimeout(() => setPhase(settledPhase), delay));
    return () => timers.forEach(window.clearTimeout);
  }, [reducedMotion, settledPhase, table.community_cards.length]);

  const activePhase = phase === "dealing-private" || phase.startsWith("revealing-")
    ? phase
    : settledPhase;
  return { phase: activePhase, revealedBySeat, boardCount };
}

function PlayingCard({
  card,
  hidden = false,
  highlighted = false,
}: {
  card?: string;
  hidden?: boolean;
  highlighted?: boolean;
}) {
  if (hidden || !card) {
    return <span className={`${styles.card} ${styles.cardBack}`} aria-label="Hidden card" />;
  }
  const rank = card.slice(0, -1);
  const suitCode = card.slice(-1);
  const red = suitCode === "d" || suitCode === "h";
  return (
    <span
      className={`${styles.card} ${red ? styles.redCard : ""} ${highlighted ? styles.bestCard : ""}`}
      aria-label={`${rank} of ${suitNames[suitCode] ?? suitCode}`}
    >
      <span>{rank}</span>
      <b>{suits[suitCode] ?? suitCode}</b>
    </span>
  );
}

function ChipTower({
  amount,
  maximum,
  tone,
}: {
  amount: number;
  maximum: number;
  tone: "balance" | "committed";
}) {
  const count = amount <= 0
    ? 0
    : Math.max(1, Math.min(5, Math.ceil((amount / Math.max(1, maximum)) * 5)));
  return (
    <span
      aria-hidden="true"
      className={`${styles.chipTower} ${styles[`chipTower${tone.charAt(0).toUpperCase()}${tone.slice(1)}`]}`}
    >
      {Array.from({ length: count }, (_, index) => (
        <i
          key={index}
          style={{ "--chip-level": index } as CSSProperties}
        />
      ))}
      {count === 0 && <i className={styles.emptyChip} />}
    </span>
  );
}

function SeatView({
  seat,
  viewerSeat,
  actingSeat,
  buttonSeat,
  revealedCount,
  result,
  latestAction,
  playerCount,
  winner,
  showdownIndex,
  bigBlind,
  maxStack,
  maxCommitted,
}: {
  seat: PlayerSeat;
  viewerSeat: number;
  actingSeat: number | null;
  buttonSeat: number;
  revealedCount: number;
  result: HandResult | null;
  latestAction?: string;
  playerCount: number;
  winner: boolean;
  showdownIndex: number;
  bigBlind: number;
  maxStack: number;
  maxCommitted: number;
}) {
  const relativePosition = (seat.seat - viewerSeat + 6) % 6;
  const resultHand = result?.revealed_hands.find((hand) => hand.seat === seat.seat);
  const cards = resultHand?.hole_cards ?? seat.hole_cards;
  const best = new Set(resultHand?.best_five ?? []);
  const showBacks = !seat.folded && !seat.eliminated && cards.length === 0;
  return (
    <article
      aria-label={`${seat.kind === "bot" ? "Bot" : "Human"} player ${seat.display_name}, seat ${seat.seat}`}
      className={[
        styles.seat,
        styles[`seatPosition${relativePosition}`],
        seat.kind === "bot" ? styles.botSeat : styles.humanSeat,
        seat.seat === viewerSeat ? styles.viewerSeat : "",
        seat.seat === actingSeat ? styles.actingSeat : "",
        seat.folded ? styles.foldedSeat : "",
        seat.eliminated ? styles.eliminatedSeat : "",
        winner ? styles.winnerSeat : "",
        resultHand ? styles.showdownSeat : "",
        playerCount === 2 && seat.seat !== viewerSeat ? styles.headsUpOpponent : "",
        playerCount === 4 ? styles[`fourSeatPosition${relativePosition}`] : "",
      ].join(" ")}
      style={resultHand ? ({ "--showdown-delay": `${Math.max(0, showdownIndex) * 650}ms` } as CSSProperties) : undefined}
    >
      {seat.seat === actingSeat && (
        <span
          aria-label={`${seat.display_name}'s turn`}
          className={styles.turnMarker}
          title={`${seat.display_name}'s turn`}
        >
          <i aria-hidden="true">▶</i>
          <b>Turn</b>
        </span>
      )}
      <div className={styles.seatCards} aria-label={`${seat.display_name}'s cards`}>
        {cards.slice(0, revealedCount).map((card) => (
          <PlayingCard card={card} highlighted={best.has(card)} key={card} />
        ))}
        {cards.slice(revealedCount).map((_, index) => <PlayingCard hidden key={index} />)}
        {showBacks && <><PlayingCard hidden /><PlayingCard hidden /></>}
      </div>
      <div className={styles.seatPanel}>
        <div className={styles.seatNameRow}>
          <span className={`${styles.playerKind} ${seat.kind === "bot" ? styles.botBadge : styles.humanBadge}`}>
            <i aria-hidden="true">{seat.kind === "bot" ? "<>" : "●"}</i>
            {seat.kind === "bot" ? "Bot" : "Human"}
          </span>
          <strong>{seat.display_name}</strong>
          {seat.seat === buttonSeat && <span className={styles.dealerChip}>D</span>}
          {winner && <span className={styles.winnerCrown} aria-label="Winner">♛</span>}
        </div>
        <span className={styles.seatState}>
          {winner ? "Winner" : seat.eliminated ? "Out" : seat.folded ? "Folded" : seat.all_in ? "All in" : "In hand"}
        </span>
      </div>
      <div
        aria-label={`${seat.display_name} has ${formatChips(seat.stack)} left and has put ${formatChips(seat.committed_this_hand)} into this hand`}
        className={styles.boardChipRack}
      >
        <span className={styles.boardChipStack} title={`${formatChips(seat.stack)} remaining`}>
          <ChipTower amount={seat.stack} maximum={maxStack} tone="balance" />
          <span className={styles.boardChipCopy}>
            <small>Chips left</small>
            <strong>{formatChips(seat.stack)}</strong>
            {seat.seat === viewerSeat && <em>{blindDepth.format(seat.stack / bigBlind)} BB</em>}
          </span>
        </span>
        <span className={styles.boardChipStack} title={`${formatChips(seat.committed_this_hand)} committed this hand`}>
          <ChipTower amount={seat.committed_this_hand} maximum={maxCommitted} tone="committed" />
          <span className={styles.boardChipCopy}>
            <small>Put in hand</small>
            <strong>{formatChips(seat.committed_this_hand)}</strong>
            {seat.committed_this_street > 0 && <em>{formatChips(seat.committed_this_street)} this round</em>}
          </span>
        </span>
      </div>
      {latestAction && <span className={styles.actionBadge}>{latestAction}</span>}
    </article>
  );
}

function turnFor(table: PlayerTableState): PublicTurn | null {
  if (table.turn) return table.turn;
  if (!table.decision) return null;
  return {
    seat: table.viewer_seat,
    kind: "human",
    deadline_at: table.decision.deadline_at,
    duration_ms: 30_000,
  };
}

function statusLabel(
  phase: PresentationPhase,
  table: PlayerTableState,
  names: Map<number, string>,
): string {
  if (phase === "dealing-private") return "Dealing Private Cards";
  if (phase === "revealing-flop") return "Dealing the Flop";
  if (phase === "revealing-turn") return "Dealing the Turn";
  if (phase === "revealing-river") return "Dealing the River";
  if (phase === "showdown") return "Showdown";
  if (phase === "complete") return "Winner Confirmed";
  const turn = turnFor(table);
  if (!turn) return "Resolving…";
  if (turn.seat === table.viewer_seat) return "Your Turn";
  const name = names.get(turn.seat) ?? `Seat ${turn.seat}`;
  return turn.kind === "bot" ? `${name} Thinking` : `${name}’s Turn`;
}

function ResultPanel({ result, names }: { result: HandResult; names: Map<number, string> }) {
  const winners = result.winner_seats
    .map((seat) => names.get(seat) ?? `Seat ${seat}`);
  const winnerHeadline = winners.length > 1
    ? `${winners.join(" + ")} split the pot`
    : winners[0] === "You" ? "You win" : `${winners[0] ?? "Winner"} wins`;
  return (
    <section className={styles.resultPanel} aria-label="Hand result">
      <span>{result.synthetic ? "Test override" : result.reason === "fold" ? "Won uncontested" : "Showdown"}</span>
      <h2>{winnerHeadline}</h2>
      {result.synthetic && <p>This result was forced for testing and was not determined by hand strength.</p>}
      {result.reason === "fold" && <p>The remaining player won after every opponent folded.</p>}
      {result.awards.map((award) => {
        const wonPot = result.winner_seats.includes(award.seat);
        return (
          <p key={award.seat}>
            <strong>{names.get(award.seat) ?? `Seat ${award.seat}`}</strong> {wonPot ? "collected" : "had"} {formatChips(award.amount)}{wonPot ? "" : " returned"}
            <small>{award.net >= 0 ? "+" : ""}{formatChips(award.net)} net</small>
          </p>
        );
      })}
      {!result.synthetic && (
        <p className={styles.settlementNote}>
          Only matched chips in the pot are awarded. Chips a player never committed stay in their stack.
        </p>
      )}
      {result.revealed_hands.map((hand) => (
        <p key={hand.seat}>
          <strong>{names.get(hand.seat) ?? `Seat ${hand.seat}`}</strong> — {hand.label}
        </p>
      ))}
    </section>
  );
}

export function PokerTableView({
  table,
  submitting,
  notice,
  error,
  connectionLabel,
  connectionTone = "live",
  embedded = false,
  fullScreen = false,
  showSidePots = true,
  animateInitialDeal = false,
  onSubmit,
}: PokerTableViewProps) {
  const { phase, revealedBySeat, boardCount } = useTablePresentation(table, animateInitialDeal);
  const [now, setNow] = useState(() => Date.now());
  const [railOpen, setRailOpen] = useState(true);
  const turn = turnFor(table);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 200);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (window.matchMedia("(max-width: 1100px)").matches) setRailOpen(false);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const names = useMemo(
    () => new Map(table.seats.map((seat) => [seat.seat, seat.display_name])),
    [table.seats],
  );
  const secondsLeft = turn
    ? Math.max(0, (Date.parse(turn.deadline_at) - now) / 1000)
    : 0;
  const timerPercent = turn
    ? Math.min(100, (secondsLeft * 1000 * 100) / turn.duration_ms)
    : 0;
  const resolving = Boolean(turn && secondsLeft <= 0);
  const decisionReady = Boolean(table.decision && phase === "awaiting-human" && !resolving);
  const recentActions = [...table.action_history].slice(-8).reverse();
  const latest = recentActions[0];
  const result = table.hand_result ?? null;
  const winnerSeats = useMemo(
    () => new Set(result?.winner_seats ?? []),
    [result],
  );
  const boardBest = new Set(result?.revealed_hands.flatMap((hand) => hand.best_five) ?? []);
  const raise = table.decision?.legal_actions.find((item) => item.action === "raise");
  const viewer = table.seats.find((seat) => seat.seat === table.viewer_seat);
  const maxStack = Math.max(1, ...table.seats.map((seat) => seat.stack));
  const maxCommitted = Math.max(1, ...table.seats.map((seat) => seat.committed_this_hand));
  const callAmount = table.decision?.legal_actions.find((item) => item.action === "call")?.amount ?? 0;
  const activeStage = currentHandStage(phase, table);
  const activeStageIndex = handStages.findIndex((stage) => stage.key === activeStage);
  const turnName = turn ? names.get(turn.seat) ?? `Seat ${turn.seat}` : null;
  const turnLabel = resolving ? "Resolving action…" : statusLabel(phase, table, names);
  const latestNarrative = actionNarrative(latest, names);
  const tableUpdate = phase === "dealing-private"
    ? "Blinds are posted. The dealer is giving every player 2 private cards."
    : phase === "revealing-flop"
      ? "The flop is being dealt: 3 shared cards for everyone to use."
      : phase === "revealing-turn"
        ? "The turn is being dealt: the 4th shared card."
        : phase === "revealing-river"
          ? "The river is being dealt: the final shared card."
          : latestNarrative ?? "The table is preparing the next decision.";

  return (
    <div className={`${styles.shell} ${embedded ? styles.embeddedShell : ""} ${fullScreen ? styles.fullScreenShell : ""}`}>
      {!embedded && (
        <header className={styles.tableHeader}>
          <Link className={styles.wordmark} href="/">ACM / POKER</Link>
          <div className={styles.handMeta}>
            <span>{table.tournament_id}</span>
            <b>Table {table.table_id.replace(/^table-?/i, "")}</b>
            <span>Hand #{table.hand_number}</span>
          </div>
          <div className={styles.headerActions}>
            <span className={`${styles.connection} ${styles[connectionTone]}`}><i aria-hidden="true" /> {connectionLabel}</span>
            <Link href="/play">Leave table</Link>
          </div>
        </header>
      )}

      <main className={`${styles.gameLayout} ${railOpen ? "" : styles.railClosed}`} id={embedded ? undefined : "main-content"}>
        <section className={styles.tableColumn} aria-label="Poker table">
          <div className={`${styles.turnBanner} ${decisionReady ? styles.yourTurnBanner : ""}`}>
            <div className={styles.turnBannerCopy}>
              <span>{activeStage === "showdown" ? "Final result" : `Stage ${activeStageIndex + 1} of ${handStages.length}`}</span>
              <h1 aria-live="polite">{turnLabel}</h1>
              <small>{turnName && !resolving ? (turn?.seat === table.viewer_seat ? "Review the table, then choose your action" : `${turnName} has the clock`) : tableUpdate}</small>
            </div>
            <div className={styles.topClock}>
              {turn && !resolving ? <strong>{secondsLeft.toFixed(1)}<small>s</small></strong> : <strong>—</strong>}
              <div className={styles.topTimerTrack} aria-label={turn ? `${secondsLeft.toFixed(1)} seconds remaining` : "No active turn"}>
                <span style={{ width: `${timerPercent}%` }} />
              </div>
            </div>
            <button
              aria-controls="hand-details"
              aria-expanded={railOpen}
              aria-label={`${railOpen ? "Hide" : "Show"} hand details`}
              className={styles.railToggle}
              onClick={() => setRailOpen((open) => !open)}
              title={`${railOpen ? "Hide" : "Show"} hand details`}
              type="button"
            >
              <span aria-hidden="true">{railOpen ? "→" : "←"}</span>
              {railOpen ? "Hide details" : "Show details"}
            </button>
          </div>

          <ol className={styles.phaseTrack} aria-label="Hand stages">
            {handStages.map((stage, index) => (
              <li
                aria-current={index === activeStageIndex ? "step" : undefined}
                className={index === activeStageIndex ? styles.activePhase : index < activeStageIndex ? styles.completePhase : ""}
                key={stage.key}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{stage.label}</strong><small>{stage.detail}</small></div>
              </li>
            ))}
          </ol>

          <div className={styles.tableStatus}>
            <span>{handStages[activeStageIndex]?.label ?? table.street}</span>
            <span>Blinds {formatChips(table.small_blind)} / {formatChips(table.big_blind)}</span>
            <span>Ante {formatChips(table.big_blind_ante)}</span>
            <span>Hand #{table.hand_number}</span>
          </div>

          <div className={styles.tableStage}>
            {!turn && !result && (
              <div className={styles.eventBanner} aria-live="polite">
                <span>Table update</span>
                <strong>{tableUpdate}</strong>
              </div>
            )}
            <div className={styles.felt}>
              <div className={styles.board}>
                <span className={styles.potLabel}>Total Pot</span>
                <strong>{formatChips(table.pot)}</strong>
                <div className={styles.communityCards}>
                  {Array.from({ length: 5 }, (_, index) =>
                    index < boardCount && table.community_cards[index] ? (
                      <PlayingCard card={table.community_cards[index]} highlighted={boardBest.has(table.community_cards[index])} key={index} />
                    ) : <span className={styles.emptyCard} key={index} />,
                  )}
                </div>
                {showSidePots && table.side_pots.map((pot, index) => (
                  <span className={styles.sidePotLabel} key={`${pot.amount}-${index}`}>
                    Side pot {index + 1}: {formatChips(pot.amount)}
                  </span>
                ))}
              </div>
            </div>
            {table.seats.map((seat) => (
              <SeatView
                seat={seat}
                viewerSeat={table.viewer_seat}
                actingSeat={turn?.seat ?? null}
                buttonSeat={table.button_seat}
                revealedCount={revealedBySeat[seat.seat] ?? 0}
                result={result}
                latestAction={latest?.seat === seat.seat ? `${actionCopy(latest.action)}${latest.amount_to !== null ? ` ${formatChips(latest.amount_to)}` : ""}` : undefined}
                playerCount={table.seats.length}
                winner={winnerSeats.has(seat.seat)}
                showdownIndex={result?.revealed_hands.findIndex((hand) => hand.seat === seat.seat) ?? -1}
                bigBlind={table.big_blind}
                maxStack={maxStack}
                maxCommitted={maxCommitted}
                key={seat.seat}
              />
            ))}
          </div>

          <div className={`${styles.actionDock} ${decisionReady ? styles.yourTurn : ""}`}>
            <div className={styles.turnCopy}>
              <span>{decisionReady ? "Your options" : result ? "Hand settled" : "Table update"}</span>
              <strong>{decisionReady ? "The table is yours—review the pot, then act" : result ? "Winner confirmed" : tableUpdate}</strong>
              {notice && <p aria-live="polite" className={styles.notice}>{notice}</p>}
              {error && <p className={styles.errorNotice} role="alert">Connection interrupted · Retrying… {error}</p>}
            </div>

            {table.decision && (
              <div className={styles.controls}>
                <div className={styles.commitmentSummary}>
                  <span>To call <b>{formatChips(callAmount)}</b></span>
                  <span>Already committed <b>{formatChips(viewer?.committed_this_street ?? 0)}</b></span>
                </div>
                <div className={styles.primaryActions}>
                  {table.decision.legal_actions.filter((item) => item.action !== "raise").map((item) => (
                    <button
                      className={item.action === "fold" ? styles.foldButton : styles.actionButton}
                      disabled={submitting || !decisionReady}
                      key={item.action}
                      onClick={() => onSubmit(item.action)}
                      type="button"
                    >
                      {actionCopy(item.action)}{item.amount !== null && <span>{formatChips(item.amount)}</span>}
                    </button>
                  ))}
                </div>
                {raise && raise.min_amount_to !== null && raise.max_amount_to !== null && (
                  <RaiseControl
                    action={raise}
                    callAmount={callAmount}
                    committed={viewer?.committed_this_street ?? 0}
                    decisionId={table.decision.decision_id}
                    disabled={submitting || !decisionReady}
                    key={`${table.decision.decision_id}-${raise.min_amount_to}-${raise.max_amount_to}`}
                    onSubmit={(amount) => onSubmit("raise", amount)}
                    pot={table.pot}
                    stack={viewer?.stack ?? 0}
                  />
                )}
              </div>
            )}
          </div>
        </section>

        <aside className={styles.handRail} hidden={!railOpen} id="hand-details">
          <div className={styles.railHead}>
            <div><span>Current hand</span><strong>#{table.hand_number}</strong></div>
            <span>{table.street}</span>
          </div>
          <dl className={styles.summary}>
            <div><dt>Total pot</dt><dd>{formatChips(table.pot)}</dd></div>
            <div><dt>Players live</dt><dd>{table.seats.filter((seat) => !seat.folded && !seat.eliminated).length}</dd></div>
            <div><dt>Your seat</dt><dd>{table.viewer_seat}</dd></div>
          </dl>
          {result && <ResultPanel result={result} names={names} />}
          <details className={styles.historyDisclosure} open>
            <summary className={styles.historyHead}><span>Action history</span><span>Latest first</span></summary>
            <ol className={styles.history}>
              {recentActions.map((action, index) => (
                <li className={index === 0 ? styles.latestHistory : ""} key={action.sequence}>
                  <span>{String(action.sequence).padStart(2, "0")}</span>
                  <div>
                    <strong>{names.get(action.seat) ?? `Seat ${action.seat}`}</strong>
                    <p>{actionCopy(action.action)}{action.amount_to !== null ? ` to ${formatChips(action.amount_to)}` : ""}{action.automatic ? ` · ${automaticActionCopy(action.failure_reason)}` : ""}</p>
                  </div>
                </li>
              ))}
            </ol>
          </details>
          <p className={styles.railFoot}>State is read-only until the server presents a legal decision.</p>
        </aside>
      </main>
    </div>
  );
}

function RaiseControl({
  action,
  pot,
  committed,
  callAmount,
  stack,
  decisionId,
  disabled,
  onSubmit,
}: {
  action: LegalAction;
  pot: number;
  committed: number;
  callAmount: number;
  stack: number;
  decisionId: string;
  disabled: boolean;
  onSubmit: (amount: number) => void;
}) {
  const min = action.min_amount_to ?? 0;
  const max = action.max_amount_to ?? min;
  const clamp = (value: number) => Math.max(min, Math.min(max, Math.round(value)));
  const [amountText, setAmountText] = useState(String(min));
  const parsed = Number(amountText);
  const amount = Number.isInteger(parsed) && amountText !== "" && parsed >= min && parsed <= max
    ? parsed
    : null;
  const additional = amount === null ? 0 : Math.max(0, amount - committed);
  const presets = [
    ["Min raise", min],
    ["½ pot", committed + callAmount + (pot + callAmount) / 2],
    ["¾ pot", committed + callAmount + (pot + callAmount) * 0.75],
    ["Pot", committed + callAmount + pot + callAmount],
    ["All in", max],
  ] as const;
  const amountHint = amountText === ""
    ? `Enter ${formatChips(min)}–${formatChips(max)}`
    : !Number.isInteger(parsed)
      ? "Use a whole-dollar amount"
      : parsed < min
        ? `Minimum raise is ${formatChips(min)}`
        : parsed > max
          ? `Maximum raise is ${formatChips(max)}`
          : `Valid range: ${formatChips(min)}–${formatChips(max)}`;

  return (
    <form
      className={styles.raiseControl}
      onSubmit={(event) => {
        event.preventDefault();
        if (amount !== null && !disabled) onSubmit(amount);
      }}
    >
      <div className={styles.raiseTopline}>
        <label htmlFor={`raise-${decisionId}`}>Raise to</label>
        <input
          aria-label="Raise amount"
          aria-describedby={`raise-hint-${decisionId}`}
          aria-invalid={amount === null}
          autoComplete="off"
          disabled={disabled}
          id={`raise-${decisionId}`}
          inputMode="numeric"
          max={max}
          min={min}
          name={`raise-${decisionId}`}
          onChange={(event) => setAmountText(event.target.value)}
          step={1}
          type="number"
          value={amountText}
        />
      </div>
      <span className={`${styles.raiseHint} ${amount === null ? styles.raiseHintError : ""}`} id={`raise-hint-${decisionId}`}>
        {amountHint}
      </span>
      <div className={styles.raiseMath}>
        <span>Adds <b>{amount === null ? "—" : formatChips(additional)}</b></span>
        <span>Stack left <b>{amount === null ? "—" : formatChips(Math.max(0, stack - additional))}</b></span>
      </div>
      <div className={styles.raiseBottom}>
        <div className={styles.presets}>
          {presets.map(([label, value]) => (
            <button disabled={disabled} key={label} onClick={() => setAmountText(String(clamp(value)))} type="button">{label}</button>
          ))}
        </div>
        <button className={styles.raiseButton} disabled={disabled || amount === null} type="submit">
          Raise <span>{amount === null ? "—" : formatChips(amount)}</span>
        </button>
      </div>
    </form>
  );
}
