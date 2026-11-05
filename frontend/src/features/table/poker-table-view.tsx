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
  exitHref?: string;
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

const chips = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const blindDepth = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const suits: Record<string, string> = { c: "♣", d: "♦", h: "♥", s: "♠" };
const suitNames: Record<string, string> = {
  c: "clubs",
  d: "diamonds",
  h: "hearts",
  s: "spades",
};
const SHORTCUTS_KEY = "acm-poker-shortcuts";

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

function ordinal(value: number): string {
  const suffix = value % 100 >= 11 && value % 100 <= 13
    ? "th"
    : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[value % 10] ?? "th";
  return `${value}${suffix}`;
}

function formatClock(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.max(0, seconds % 60)).padStart(2, "0")}`;
}

function actionCopy(action: ActionType, betting: boolean): string {
  if (action === "raise") return betting ? "Bet" : "Raise";
  return action.charAt(0).toUpperCase() + action.slice(1);
}

type HistoryEntry = PlayerTableState["action_history"][number];

/** A raise is a "bet" when nobody has bet earlier on the same post-flop street. */
function isOpeningBet(action: HistoryEntry, history: HistoryEntry[]): boolean {
  if (action.action !== "raise" || !action.street || action.street === "preflop") return false;
  return !history.some(
    (other) => other.sequence < action.sequence && other.street === action.street && other.action === "raise",
  );
}

function actionLabel(action: HistoryEntry, history: HistoryEntry[]): string {
  if (action.action === "raise") return isOpeningBet(action, history) ? "Bet" : "Raise";
  return action.action.charAt(0).toUpperCase() + action.action.slice(1);
}

function actionNarrative(
  action: HistoryEntry | undefined,
  history: HistoryEntry[],
  names: Map<number, string>,
): string | null {
  if (!action) return null;
  const name = names.get(action.seat) ?? `Seat ${action.seat}`;
  const automatic = action.automatic ? " automatically" : "";
  if (action.action === "fold") return `${name}${automatic} folded.`;
  if (action.action === "check") return `${name}${automatic} checked.`;
  if (action.action === "call") return `${name}${automatic} called.`;
  const verb = isOpeningBet(action, history) ? "bet" : "raised to";
  return `${name}${automatic} ${verb} ${formatChips(action.amount_to ?? 0)}.`;
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
      aria-label={`${rank === "T" ? "10" : rank} of ${suitNames[suitCode] ?? suitCode}`}
    >
      <span>{rank === "T" ? "10" : rank}</span>
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
  anchorSeat,
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
  viewerSeat: number | null;
  anchorSeat: number;
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
  const relativePosition = (seat.seat - anchorSeat + 6) % 6;
  const resultHand = result?.revealed_hands.find((hand) => hand.seat === seat.seat);
  const cards = resultHand?.hole_cards ?? seat.hole_cards;
  const best = new Set(resultHand?.best_five ?? []);
  const showBacks = !seat.folded && !seat.eliminated && cards.length === 0;
  const isViewer = seat.seat === viewerSeat;
  return (
    <article
      aria-label={`${seat.kind === "bot" ? "Bot" : "Human"} player ${seat.display_name}, seat ${seat.seat}`}
      className={[
        styles.seat,
        styles[`seatPosition${relativePosition}`],
        seat.kind === "bot" ? styles.botSeat : styles.humanSeat,
        isViewer ? styles.viewerSeat : "",
        seat.seat === actingSeat ? styles.actingSeat : "",
        seat.folded ? styles.foldedSeat : "",
        seat.eliminated ? styles.eliminatedSeat : "",
        winner ? styles.winnerSeat : "",
        resultHand ? styles.showdownSeat : "",
        playerCount === 2 && seat.seat !== anchorSeat ? styles.headsUpOpponent : "",
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
          <strong>{isViewer ? `${seat.display_name} (you)` : seat.display_name}</strong>
          {seat.seat === buttonSeat && <span className={styles.dealerChip} title="Dealer button">D</span>}
          {winner && <span className={styles.winnerCrown} aria-label="Winner">♛</span>}
        </div>
        <span className={styles.seatState}>
          {winner
            ? "Winner"
            : seat.eliminated
              ? "Out"
              : seat.folded
                ? "Folded"
                : seat.all_in
                  ? "All in"
                  : seat.away
                    ? "Away"
                    : "In hand"}
        </span>
      </div>
      <div
        aria-label={`${seat.display_name} has ${formatChips(seat.stack)} chips left and has put ${formatChips(seat.committed_this_hand)} into this hand`}
        className={styles.boardChipRack}
      >
        <span className={styles.boardChipStack} title={`${formatChips(seat.stack)} chips remaining`}>
          <ChipTower amount={seat.stack} maximum={maxStack} tone="balance" />
          <span className={styles.boardChipCopy}>
            <small>Chips left</small>
            <strong>{formatChips(seat.stack)}</strong>
            {isViewer && <em>{blindDepth.format(seat.stack / bigBlind)} BB</em>}
          </span>
        </span>
        <span className={styles.boardChipStack} title={`${formatChips(seat.committed_this_hand)} chips committed this hand`}>
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
  if (!table.decision || table.viewer_seat === null) return null;
  return {
    seat: table.viewer_seat,
    kind: "human",
    deadline_at: table.decision.deadline_at,
    duration_ms: table.decision.duration_ms,
  };
}

function statusLabel(
  phase: PresentationPhase,
  table: PlayerTableState,
  names: Map<number, string>,
  waitSeconds: number | null,
): string {
  if (phase === "dealing-private") return "Dealing Private Cards";
  if (phase === "revealing-flop") return "Dealing the Flop";
  if (phase === "revealing-turn") return "Dealing the Turn";
  if (phase === "revealing-river") return "Dealing the River";
  if (phase === "showdown") return "Showdown";
  if (phase === "complete") return "Hand Complete";
  const turn = turnFor(table);
  if (!turn) return waitSeconds !== null ? "Next Action Shortly" : "Resolving…";
  if (turn.seat === table.viewer_seat) return "Your Turn";
  const name = names.get(turn.seat) ?? `Seat ${turn.seat}`;
  return turn.kind === "bot" ? `${name} Thinking` : `${name}’s Turn`;
}

function statusBanner(table: PlayerTableState): { tone: "info" | "warning"; copy: string } | null {
  const viewerSeat = table.seats.find((seat) => seat.seat === table.viewer_seat);
  if (table.table_status === "quarantined") {
    return { tone: "warning", copy: "This table stopped after an engine error. The organizer can see it and will end or restart the match." };
  }
  if (table.match_status === "paused") {
    return { tone: "info", copy: "The organizer paused the match. Play resumes from the next hand." };
  }
  if (table.match_status === "pause_requested") {
    return { tone: "info", copy: "The organizer will pause the match after this hand." };
  }
  if (table.match?.end_requested && table.match_status !== "completed") {
    return { tone: "info", copy: "Final hand: the organizer is ending the match after this hand." };
  }
  if (viewerSeat?.away) {
    return { tone: "warning", copy: "You missed your last turns and are marked away, so your clock is short. Act once to return." };
  }
  return null;
}

function ResultPanel({ result, names, title }: { result: HandResult; names: Map<number, string>; title?: string }) {
  const winners = result.winner_seats.map((seat) => names.get(seat) ?? `Seat ${seat}`);
  const winnerHeadline = winners.length > 1
    ? `${winners.join(" + ")} split the pot`
    : `${winners[0] ?? "Winner"} wins`;
  return (
    <section className={styles.resultPanel} aria-label={title ?? "Hand result"}>
      <span>{title ?? (result.reason === "fold" ? "Won uncontested" : "Showdown")}</span>
      <h2>{winnerHeadline}</h2>
      {result.reason === "fold" && <p>Everyone else folded.</p>}
      {result.awards.map((award) => {
        const wonPot = result.winner_seats.includes(award.seat);
        return (
          <p key={award.seat}>
            <strong>{names.get(award.seat) ?? `Seat ${award.seat}`}</strong> {wonPot ? "collected" : "had"} {formatChips(award.amount)}{wonPot ? "" : " returned"}
            <small>{award.net >= 0 ? "+" : ""}{formatChips(award.net)} net</small>
          </p>
        );
      })}
      {result.revealed_hands.map((hand) => (
        <p key={hand.seat}>
          <strong>{names.get(hand.seat) ?? `Seat ${hand.seat}`}</strong> — {hand.label}
        </p>
      ))}
    </section>
  );
}

function FinishOverlay({ table, exitHref }: { table: PlayerTableState; exitHref: string }) {
  const [hidden, setHidden] = useState(false);
  const viewer = table.viewer;
  const standings = table.match?.standings ?? [];
  const finished = table.match_status === "completed" || table.match_status === "cancelled";
  if (!finished && viewer?.status !== "eliminated") return null;
  if (hidden) {
    return (
      <button className={styles.finishReopen} onClick={() => setHidden(false)} type="button">
        Show standings
      </button>
    );
  }
  const headline = viewer?.status === "winner"
    ? "You won the match"
    : viewer?.finish_position
      ? `You finished ${ordinal(viewer.finish_position)}`
      : table.match_status === "cancelled"
        ? "Match cancelled"
        : "Match finished";
  return (
    <div className={styles.finishOverlay} role="dialog" aria-label="Match result">
      <div>
        <span>{finished ? "Final standings" : "You are out"}</span>
        <h2>{headline}</h2>
        {!finished && <p>The match continues without you. You can keep watching from here.</p>}
        {standings.length > 0 && (
          <ol>
            {standings.map((item) => (
              <li key={item.entry_id} data-me={item.entry_id === viewer?.entry_id ? "true" : undefined}>
                <b>{ordinal(item.position)}</b>
                <span>{item.display_name}{item.kind === "bot" ? " · bot" : ""}</span>
                <small>{item.final_stack > 0 ? `${formatChips(item.final_stack)} chips` : `out on hand ${item.eliminated_hand_number ?? "—"}`}</small>
              </li>
            ))}
          </ol>
        )}
        <div className={styles.finishActions}>
          <Link href={exitHref}>Back to dashboard</Link>
          <button onClick={() => setHidden(true)} type="button">
            {finished ? "See the final hand" : "Keep watching"}
          </button>
        </div>
      </div>
    </div>
  );
}

function useShortcutPreference(): [boolean, (value: boolean) => void] {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setEnabled(window.localStorage.getItem(SHORTCUTS_KEY) === "on"), 0);
    return () => window.clearTimeout(timer);
  }, []);
  return [
    enabled,
    (value: boolean) => {
      setEnabled(value);
      window.localStorage.setItem(SHORTCUTS_KEY, value ? "on" : "off");
    },
  ];
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
  exitHref = "/dashboard",
  onSubmit,
}: PokerTableViewProps) {
  const { phase, revealedBySeat, boardCount } = useTablePresentation(table, animateInitialDeal);
  const [now, setNow] = useState(() => Date.now());
  const [railOpen, setRailOpen] = useState(true);
  const [shortcuts, setShortcuts] = useShortcutPreference();
  const [foldArmed, setFoldArmed] = useState(false);
  const raiseInputRef = useRef<HTMLInputElement>(null);
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
  const lastHandNames = useMemo(
    () => new Map(Object.entries(table.last_hand?.names ?? {}).map(([seat, name]) => [Number(seat), name])),
    [table.last_hand],
  );
  const secondsLeft = turn ? Math.max(0, (Date.parse(turn.deadline_at) - now) / 1000) : 0;
  const timerPercent = turn ? Math.min(100, (secondsLeft * 1000 * 100) / turn.duration_ms) : 0;
  const resolving = Boolean(turn && secondsLeft <= 0);
  const decisionReady = Boolean(table.decision && phase === "awaiting-human" && !resolving);
  const waitSeconds = table.next_action_at
    ? Math.max(0, (Date.parse(table.next_action_at) - now) / 1000)
    : null;
  const recentActions = [...table.action_history].slice(-8).reverse();
  const latest = recentActions[0];
  const result = table.hand_result ?? null;
  const winnerSeats = useMemo(() => new Set(result?.winner_seats ?? []), [result]);
  const boardBest = new Set(result?.revealed_hands.flatMap((hand) => hand.best_five) ?? []);
  const legal = table.decision?.legal_actions ?? [];
  const raise = legal.find((item) => item.action === "raise");
  const canCheck = legal.some((item) => item.action === "check");
  const callAction = legal.find((item) => item.action === "call");
  const betting = canCheck;
  const viewer = table.seats.find((seat) => seat.seat === table.viewer_seat);
  const anchorSeat = table.viewer_seat ?? 1;
  const maxStack = Math.max(1, ...table.seats.map((seat) => seat.stack));
  const maxCommitted = Math.max(1, ...table.seats.map((seat) => seat.committed_this_hand));
  const callAmount = callAction?.amount ?? 0;
  const activeStage = currentHandStage(phase, table);
  const activeStageIndex = handStages.findIndex((stage) => stage.key === activeStage);
  const turnName = turn ? names.get(turn.seat) ?? `Seat ${turn.seat}` : null;
  const turnLabel = resolving ? "Resolving action…" : statusLabel(phase, table, names, waitSeconds);
  const latestNarrative = actionNarrative(latest, table.action_history, names);
  const banner = statusBanner(table);
  const spectating = table.viewer_seat === null || table.viewer?.status !== "seated";
  const tableUpdate = phase === "dealing-private"
    ? "Blinds are posted. The dealer is giving every player 2 private cards."
    : phase === "revealing-flop"
      ? "The flop is being dealt: 3 shared cards for everyone to use."
      : phase === "revealing-turn"
        ? "The turn is being dealt: the 4th shared card."
        : phase === "revealing-river"
          ? "The river is being dealt: the final shared card."
          : latestNarrative ?? "The table is preparing the next decision.";

  useEffect(() => {
    if (!shortcuts || !decisionReady || submitting) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "c") {
        event.preventDefault();
        if (canCheck) onSubmit("check");
        else if (callAction) onSubmit("call");
      } else if (key === "f") {
        event.preventDefault();
        if (canCheck && !foldArmed) {
          setFoldArmed(true);
          return;
        }
        setFoldArmed(false);
        onSubmit("fold");
      } else if ((key === "r" || key === "b") && raise) {
        event.preventDefault();
        raiseInputRef.current?.focus();
        raiseInputRef.current?.select();
      } else if (key === "escape") {
        setFoldArmed(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [callAction, canCheck, decisionReady, foldArmed, onSubmit, raise, shortcuts, submitting]);

  useEffect(() => {
    if (!table.decision) {
      const timer = window.setTimeout(() => setFoldArmed(false), 0);
      return () => window.clearTimeout(timer);
    }
  }, [table.decision]);

  return (
    <div className={`${styles.shell} ${embedded ? styles.embeddedShell : ""} ${fullScreen ? styles.fullScreenShell : ""}`}>
      {!embedded && (
        <header className={styles.tableHeader}>
          <Link className={styles.wordmark} href="/">ACM / POKER</Link>
          <div className={styles.handMeta}>
            <span>{table.match?.name ?? "Match"}</span>
            <b>Hand #{table.hand_number}</b>
            <span>{table.match ? `${table.match.players_remaining} players left` : ""}</span>
          </div>
          <div className={styles.headerActions}>
            <span className={`${styles.connection} ${styles[connectionTone]}`}><i aria-hidden="true" /> {connectionLabel}</span>
            <Link href={exitHref}>Leave table</Link>
          </div>
        </header>
      )}

      <main className={`${styles.gameLayout} ${railOpen ? "" : styles.railClosed}`} id={embedded ? undefined : "main-content"}>
        <section className={styles.tableColumn} aria-label="Poker table">
          <div className={`${styles.turnBanner} ${decisionReady ? styles.yourTurnBanner : ""}`}>
            <div className={styles.turnBannerCopy}>
              <span>{activeStage === "showdown" ? "Final result" : `Stage ${activeStageIndex + 1} of ${handStages.length}`}</span>
              <h1 aria-live="polite">{turnLabel}</h1>
              <small>
                {turnName && !resolving
                  ? (turn?.seat === table.viewer_seat ? "Review the table, then choose your action" : `${turnName} has the clock`)
                  : waitSeconds !== null && !turn
                    ? `Pausing so everyone can follow · ${waitSeconds.toFixed(1)}s`
                    : tableUpdate}
              </small>
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

          {banner && (
            <p className={styles.statusBanner} data-tone={banner.tone} role="status">{banner.copy}</p>
          )}

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
            {table.big_blind_ante > 0 && <span>Ante {formatChips(table.big_blind_ante)}</span>}
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
                anchorSeat={anchorSeat}
                actingSeat={turn?.seat ?? null}
                buttonSeat={table.button_seat}
                revealedCount={revealedBySeat[seat.seat] ?? 0}
                result={result}
                latestAction={latest?.seat === seat.seat ? `${actionLabel(latest, table.action_history)}${latest.amount_to !== null ? ` ${formatChips(latest.amount_to)}` : ""}` : undefined}
                playerCount={table.seats.length}
                winner={winnerSeats.has(seat.seat)}
                showdownIndex={result?.revealed_hands.findIndex((hand) => hand.seat === seat.seat) ?? -1}
                bigBlind={table.big_blind}
                maxStack={maxStack}
                maxCommitted={maxCommitted}
                key={seat.seat}
              />
            ))}
            <FinishOverlay exitHref={exitHref} table={table} />
          </div>

          <div className={`${styles.actionDock} ${decisionReady ? styles.yourTurn : ""}`}>
            <div className={styles.turnCopy}>
              <span>{decisionReady ? "Your options" : result ? "Hand settled" : spectating ? "Watching" : "Table update"}</span>
              <strong>{decisionReady ? "The table is yours—review the pot, then act" : result ? "Winner confirmed" : tableUpdate}</strong>
              {foldArmed && <p className={styles.notice} role="alert">Checking is free. Press F again to fold anyway, or C to check.</p>}
              {notice && !foldArmed && <p aria-live="polite" className={styles.notice}>{notice}</p>}
              {error && <p className={styles.errorNotice} role="alert">Connection interrupted · Retrying… {error}</p>}
              {!spectating && (
                <label className={styles.shortcutToggle}>
                  <input checked={shortcuts} onChange={(event) => setShortcuts(event.target.checked)} type="checkbox" />
                  Keyboard shortcuts {shortcuts ? "on: C check/call · F fold · B/R bet or raise" : "off"}
                </label>
              )}
            </div>

            {table.decision && (
              <div className={styles.controls}>
                <div className={styles.commitmentSummary}>
                  <span>To call <b>{formatChips(callAmount)}</b></span>
                  <span>Already in this round <b>{formatChips(viewer?.committed_this_street ?? 0)}</b></span>
                </div>
                <div className={styles.primaryActions}>
                  {legal.filter((item) => item.action !== "raise").map((item) => (
                    <button
                      className={item.action === "fold" ? styles.foldButton : styles.actionButton}
                      disabled={submitting || !decisionReady}
                      key={item.action}
                      onClick={() => onSubmit(item.action)}
                      title={canCheck && item.action === "fold" ? "Checking is free; folding gives up the hand" : undefined}
                      type="button"
                    >
                      {actionCopy(item.action, betting)}{item.amount !== null && <span>{formatChips(item.amount)}</span>}
                    </button>
                  ))}
                </div>
                {raise && raise.min_amount_to !== null && raise.max_amount_to !== null && (
                  <RaiseControl
                    action={raise}
                    betting={betting}
                    callAmount={callAmount}
                    committed={viewer?.committed_this_street ?? 0}
                    decisionId={table.decision.decision_id}
                    disabled={submitting || !decisionReady}
                    inputRef={raiseInputRef}
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
            <div><dt>Players in hand</dt><dd>{table.seats.filter((seat) => !seat.folded && !seat.eliminated).length}</dd></div>
            {table.match && <div><dt>Players left</dt><dd>{table.match.players_remaining}</dd></div>}
            {table.match && <div><dt>Blind level</dt><dd>{table.match.level_number}</dd></div>}
            {table.match?.next_big_blind && (
              <div>
                <dt>Next blinds</dt>
                <dd>
                  {formatChips(table.match.next_small_blind ?? 0)} / {formatChips(table.match.next_big_blind)}
                  {table.match.level_remaining_seconds !== null ? ` in ${formatClock(table.match.level_remaining_seconds)}` : ""}
                </dd>
              </div>
            )}
            {table.viewer_seat !== null && <div><dt>Your seat</dt><dd>{table.viewer_seat}</dd></div>}
          </dl>
          {result && <ResultPanel result={result} names={names} />}
          {!result && table.last_hand && (
            <details className={styles.historyDisclosure}>
              <summary className={styles.historyHead}>
                <span>Previous hand #{table.last_hand.hand_number}</span><span>Review</span>
              </summary>
              <div className={styles.communityCards}>
                {table.last_hand.community_cards.map((card) => <PlayingCard card={card} key={card} />)}
              </div>
              <ResultPanel result={table.last_hand.result} names={lastHandNames} title="Previous hand" />
            </details>
          )}
          <details className={styles.historyDisclosure} open>
            <summary className={styles.historyHead}><span>Action history</span><span>Latest first</span></summary>
            <ol className={styles.history}>
              {recentActions.map((action, index) => (
                <li className={index === 0 ? styles.latestHistory : ""} key={action.sequence}>
                  <span>{String(action.sequence).padStart(2, "0")}</span>
                  <div>
                    <strong>{names.get(action.seat) ?? `Seat ${action.seat}`}</strong>
                    <p>
                      {action.street ? `${action.street} · ` : ""}
                      {actionLabel(action, table.action_history)}{action.amount_to !== null ? ` to ${formatChips(action.amount_to)}` : ""}
                      {action.automatic ? ` · ${automaticActionCopy(action.failure_reason)}` : ""}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </details>
          <p className={styles.railFoot}>Chips are play money. The server decides every legal action.</p>
        </aside>
      </main>
    </div>
  );
}

function RaiseControl({
  action,
  betting,
  pot,
  committed,
  callAmount,
  stack,
  decisionId,
  disabled,
  inputRef,
  onSubmit,
}: {
  action: LegalAction;
  betting: boolean;
  pot: number;
  committed: number;
  callAmount: number;
  stack: number;
  decisionId: string;
  disabled: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
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
  const verb = betting ? "Bet" : "Raise";
  const allIn = amount !== null && amount === max;
  const potAfterCall = pot + callAmount;
  const presets = [
    [betting ? "Min bet" : "Min raise", min],
    ["½ pot", committed + callAmount + potAfterCall / 2],
    ["¾ pot", committed + callAmount + potAfterCall * 0.75],
    ["Pot", committed + callAmount + potAfterCall],
    ["All in", max],
  ] as const;
  const amountHint = amountText === ""
    ? `Enter ${formatChips(min)}–${formatChips(max)}`
    : !Number.isInteger(parsed)
      ? "Use a whole number of chips"
      : parsed < min
        ? `Minimum ${verb.toLowerCase()} is ${formatChips(min)}`
        : parsed > max
          ? `Maximum is ${formatChips(max)} (all in)`
          : `Total for this round, ${formatChips(min)}–${formatChips(max)}`;

  return (
    <form
      className={styles.raiseControl}
      onSubmit={(event) => {
        event.preventDefault();
        if (amount !== null && !disabled) onSubmit(amount);
      }}
    >
      <div className={styles.raiseTopline}>
        <label htmlFor={`raise-${decisionId}`}>{verb} to</label>
        <input
          aria-label={`${verb} amount`}
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
          ref={inputRef}
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
          {allIn ? "All in" : verb} <span>{amount === null ? "—" : formatChips(amount)}</span>
        </button>
      </div>
    </form>
  );
}
