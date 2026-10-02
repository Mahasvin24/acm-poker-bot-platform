"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { getTableState, submitTableAction, TableApiError } from "./api";
import { createDemoTableState } from "./demo-state";
import styles from "./poker-table.module.css";
import type {
  ActionSubmission,
  ActionType,
  LegalAction,
  PlayerSeat,
  PlayerTableState,
} from "./types";

type ConnectionState = "syncing" | "live" | "reconnecting" | "demo";

interface PokerTableProps {
  tournamentId: string;
}

interface AccessIssue {
  title: string;
  message: string;
  status?: number;
}

const chips = new Intl.NumberFormat("en-US");
const suits: Record<string, string> = {
  c: "♣",
  d: "♦",
  h: "♥",
  s: "♠",
};

function formatChips(value: number): string {
  return chips.format(value);
}

function actionCopy(action: ActionType): string {
  return action.charAt(0).toUpperCase() + action.slice(1);
}

function issueFromError(error: unknown): AccessIssue {
  if (error instanceof TableApiError) {
    if (error.status === 401) {
      return {
        status: error.status,
        title: "Sign in required",
        message: "Your table is private. Sign in with your tournament account, then try again.",
      };
    }
    if (error.status === 403) {
      return {
        status: error.status,
        title: "No player entry found",
        message: "This account is not registered as a human entrant in this tournament.",
      };
    }
    if (error.status === 404) {
      return {
        status: error.status,
        title: "Waiting for a seat",
        message: "The tournament has not assigned this entrant to an active table yet.",
      };
    }
    return { status: error.status, title: "Table unavailable", message: error.message };
  }
  return {
    title: "Connection interrupted",
    message: "The table could not be reached. Your chips and cards remain safe on the server.",
  };
}

function PlayingCard({ card, hidden = false }: { card?: string; hidden?: boolean }) {
  if (hidden || !card) {
    return <span className={`${styles.card} ${styles.cardBack}`} aria-label="Hidden card" />;
  }
  const rank = card.slice(0, -1);
  const suitCode = card.slice(-1);
  const red = suitCode === "d" || suitCode === "h";
  return (
    <span
      className={`${styles.card} ${red ? styles.redCard : ""}`}
      aria-label={`${rank} of ${suitCode}`}
    >
      <span>{rank}</span>
      <b>{suits[suitCode] ?? suitCode}</b>
    </span>
  );
}

function SeatView({
  seat,
  viewerSeat,
  actingSeat,
  buttonSeat,
}: {
  seat: PlayerSeat;
  viewerSeat: number;
  actingSeat: number | null;
  buttonSeat: number;
}) {
  const relativePosition = (seat.seat - viewerSeat + 6) % 6;
  const positionClass = styles[`seatPosition${relativePosition}`];
  const showBacks = !seat.folded && !seat.eliminated && seat.hole_cards.length === 0;
  return (
    <article
      className={[
        styles.seat,
        positionClass,
        seat.seat === viewerSeat ? styles.viewerSeat : "",
        seat.seat === actingSeat ? styles.actingSeat : "",
        seat.folded ? styles.foldedSeat : "",
        seat.eliminated ? styles.eliminatedSeat : "",
      ].join(" ")}
    >
      <div className={styles.seatCards}>
        {seat.hole_cards.map((card) => (
          <PlayingCard card={card} key={card} />
        ))}
        {showBacks && (
          <>
            <PlayingCard hidden />
            <PlayingCard hidden />
          </>
        )}
      </div>
      <div className={styles.seatPanel}>
        <div className={styles.seatNameRow}>
          <span className={styles.playerKind}>{seat.kind === "bot" ? "BOT" : "HUM"}</span>
          <strong>{seat.display_name}</strong>
          {seat.seat === buttonSeat && <span className={styles.dealerChip}>D</span>}
        </div>
        <span className={styles.stack}>{formatChips(seat.stack)}</span>
        {seat.all_in && <span className={styles.seatState}>All in</span>}
        {seat.folded && <span className={styles.seatState}>Folded</span>}
      </div>
      {seat.committed_this_street > 0 && (
        <span className={styles.betChip}>{formatChips(seat.committed_this_street)}</span>
      )}
    </article>
  );
}

function applyDemoAction(
  state: PlayerTableState,
  submission: ActionSubmission,
): PlayerTableState {
  const viewer = state.seats.find((seat) => seat.seat === state.viewer_seat);
  if (!viewer) return state;
  const legal = state.decision?.legal_actions.find((item) => item.action === submission.action);
  const delta =
    submission.action === "call"
      ? legal?.amount ?? 0
      : submission.action === "raise"
        ? Math.max(0, (submission.amount_to ?? 0) - viewer.committed_this_street)
        : 0;
  return {
    ...state,
    table_version: state.table_version + 1,
    acting_seat: 1,
    pot: state.pot + delta,
    decision: null,
    seats: state.seats.map((seat) =>
      seat.seat === state.viewer_seat
        ? {
            ...seat,
            stack: Math.max(0, seat.stack - delta),
            committed_this_street: seat.committed_this_street + delta,
            committed_this_hand: seat.committed_this_hand + delta,
            folded: submission.action === "fold",
          }
        : seat,
    ),
    action_history: [
      ...state.action_history,
      {
        sequence: state.action_history.length + 8,
        seat: state.viewer_seat,
        action: submission.action,
        amount_to: submission.amount_to ?? null,
        automatic: false,
      },
    ],
  };
}

export function PokerTable({ tournamentId }: PokerTableProps) {
  const demoMode = tournamentId === "demo";
  const [table, setTable] = useState<PlayerTableState | null>(null);
  const [connection, setConnection] = useState<ConnectionState>(
    demoMode ? "demo" : "syncing",
  );
  const [issue, setIssue] = useState<AccessIssue | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (demoMode) {
      const timer = window.setTimeout(() => setTable(createDemoTableState()), 0);
      return () => window.clearTimeout(timer);
    }

    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;

    const poll = async () => {
      controller = new AbortController();
      try {
        const next = await getTableState(tournamentId, controller.signal);
        if (stopped) return;
        setTable(next);
        setIssue(null);
        setConnection("live");
        timer = setTimeout(poll, next.decision ? 750 : 1800);
      } catch (error) {
        if (stopped || (error instanceof DOMException && error.name === "AbortError")) return;
        const nextIssue = issueFromError(error);
        setIssue(nextIssue);
        setConnection("reconnecting");
        if (!nextIssue.status || nextIssue.status >= 500) timer = setTimeout(poll, 2500);
      }
    };

    void poll();
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [demoMode, refreshToken, tournamentId]);

  useEffect(() => {
    if (!table?.decision) return;
    const update = () => setNow(Date.now());
    update();
    const timer = window.setInterval(update, 200);
    return () => window.clearInterval(timer);
  }, [table?.decision]);

  const decision = table?.decision ?? null;
  const raiseAction = decision?.legal_actions.find((item) => item.action === "raise");

  const secondsLeft = decision
    ? Math.max(0, (new Date(decision.deadline_at).getTime() - now) / 1000)
    : 0;
  const deadlinePassed = Boolean(decision && now > 0 && secondsLeft <= 0);

  const seatNames = useMemo(
    () => new Map(table?.seats.map((seat) => [seat.seat, seat.display_name]) ?? []),
    [table?.seats],
  );

  const submit = async (action: ActionType, amountTo?: number) => {
    if (!table?.decision || submitting || deadlinePassed) return;
    const submission: ActionSubmission = {
      decision_id: table.decision.decision_id,
      table_version: table.decision.table_version,
      action,
      ...(action === "raise" ? { amount_to: amountTo } : {}),
    };
    setSubmitting(true);
    setNotice(null);
    try {
      if (demoMode) {
        setTable((current) => (current ? applyDemoAction(current, submission) : current));
      } else {
        setTable(await submitTableAction(tournamentId, submission));
      }
      setNotice(`${actionCopy(action)} accepted`);
    } catch (error) {
      if (error instanceof TableApiError && error.status === 409) {
        setNotice("The table advanced before that action arrived. Resyncing now.");
        try {
          setTable(await getTableState(tournamentId));
        } catch (syncError) {
          setIssue(issueFromError(syncError));
        }
      } else {
        setIssue(issueFromError(error));
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (!table) {
    return (
      <main className={styles.gate}>
        <div className={styles.gateCard}>
          <Link className={styles.wordmark} href="/">ACM / POKER</Link>
          {issue ? (
            <>
              <p className={styles.kicker}>Player table</p>
              <h1>{issue.title}</h1>
              <p>{issue.message}</p>
              <div className={styles.gateActions}>
                <button type="button" onClick={() => setRefreshToken((value) => value + 1)}>
                  Try again
                </button>
                <Link href="/play">Change tournament</Link>
              </div>
            </>
          ) : (
            <>
              <span className={styles.loader} aria-hidden="true" />
              <h1>Finding your table</h1>
              <p>Syncing the latest committed hand and seat assignment.</p>
            </>
          )}
        </div>
      </main>
    );
  }

  const actingName = table.acting_seat ? seatNames.get(table.acting_seat) : null;
  const recentActions = [...table.action_history].slice(-8).reverse();

  return (
    <div className={styles.shell}>
      <header className={styles.tableHeader}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <div className={styles.handMeta}>
          <span>{table.tournament_id}</span>
          <b>Table {table.table_id.replace(/^table-?/i, "")}</b>
          <span>Hand #{table.hand_number}</span>
        </div>
        <div className={styles.headerActions}>
          <span className={`${styles.connection} ${styles[connection]}`}>
            <i /> {connection === "demo" ? "Demo table" : connection}
          </span>
          <Link href="/play">Leave table</Link>
        </div>
      </header>

      <main className={styles.gameLayout}>
        <section className={styles.tableColumn} aria-label="Poker table">
          <div className={styles.tableStatus}>
            <span>{table.street}</span>
            <span>Blinds {formatChips(table.small_blind)} / {formatChips(table.big_blind)}</span>
            <span>Ante {formatChips(table.big_blind_ante)}</span>
            <span>Version {table.table_version}</span>
          </div>

          <div className={styles.tableStage}>
            <div className={styles.felt}>
              <div className={styles.board}>
                <span className={styles.potLabel}>Pot</span>
                <strong>{formatChips(table.pot)}</strong>
                <div className={styles.communityCards}>
                  {Array.from({ length: 5 }, (_, index) =>
                    table.community_cards[index] ? (
                      <PlayingCard card={table.community_cards[index]} key={index} />
                    ) : (
                      <span className={styles.emptyCard} key={index} />
                    ),
                  )}
                </div>
                {table.side_pots.length > 0 && (
                  <span className={styles.sidePotLabel}>
                    {table.side_pots.length} side {table.side_pots.length === 1 ? "pot" : "pots"}
                  </span>
                )}
              </div>
            </div>
            {table.seats.map((seat) => (
              <SeatView
                seat={seat}
                viewerSeat={table.viewer_seat}
                actingSeat={table.acting_seat}
                buttonSeat={table.button_seat}
                key={seat.seat}
              />
            ))}
          </div>

          <div className={`${styles.actionDock} ${decision ? styles.yourTurn : ""}`}>
            <div className={styles.turnCopy}>
              {decision ? (
                <>
                  <div className={styles.turnHeading}>
                    <span>Your decision</span>
                    <strong className={deadlinePassed ? styles.expired : ""}>
                      {deadlinePassed ? "Expired" : `${secondsLeft.toFixed(1)}s`}
                    </strong>
                  </div>
                  <div className={styles.timerTrack}>
                    <span
                      style={{
                        width: `${Math.min(100, (secondsLeft / 30) * 100)}%`,
                      }}
                    />
                  </div>
                </>
              ) : (
                <>
                  <span>{table.completed ? "Hand complete" : "Waiting for action"}</span>
                  <strong>{actingName ?? "Table resolving"}</strong>
                </>
              )}
              {notice && <p className={styles.notice}>{notice}</p>}
            </div>

            {decision && (
              <div className={styles.controls}>
                <div className={styles.primaryActions}>
                  {decision.legal_actions
                    .filter((item) => item.action !== "raise")
                    .map((item) => (
                      <button
                        className={item.action === "fold" ? styles.foldButton : styles.actionButton}
                        disabled={submitting || deadlinePassed}
                        key={item.action}
                        onClick={() => void submit(item.action)}
                        type="button"
                      >
                        {actionCopy(item.action)}
                        {item.amount !== null && <span>{formatChips(item.amount)}</span>}
                      </button>
                    ))}
                </div>
                {raiseAction &&
                  raiseAction.min_amount_to !== null &&
                  raiseAction.max_amount_to !== null && (
                    <RaiseControl
                      action={raiseAction}
                      pot={table.pot}
                      key={decision.decision_id}
                      committed={
                        table.seats.find((seat) => seat.seat === table.viewer_seat)
                          ?.committed_this_street ?? 0
                      }
                      disabled={submitting || deadlinePassed}
                      onSubmit={(amount) => void submit("raise", amount)}
                    />
                  )}
              </div>
            )}
          </div>
        </section>

        <aside className={styles.handRail}>
          <div className={styles.railHead}>
            <div><span>Current hand</span><strong>#{table.hand_number}</strong></div>
            <span>{table.street}</span>
          </div>
          <dl className={styles.summary}>
            <div><dt>Main pot</dt><dd>{formatChips(table.pot)}</dd></div>
            <div><dt>Players live</dt><dd>{table.seats.filter((seat) => !seat.folded && !seat.eliminated).length}</dd></div>
            <div><dt>Your seat</dt><dd>{table.viewer_seat}</dd></div>
          </dl>
          <div className={styles.historyHead}><span>Action</span><span>Latest first</span></div>
          <ol className={styles.history}>
            {recentActions.map((action) => (
              <li key={action.sequence}>
                <span>{String(action.sequence).padStart(2, "0")}</span>
                <div>
                  <strong>{seatNames.get(action.seat) ?? `Seat ${action.seat}`}</strong>
                  <p>
                    {actionCopy(action.action)}
                    {action.amount_to !== null ? ` to ${formatChips(action.amount_to)}` : ""}
                    {action.automatic ? " · timed out" : ""}
                  </p>
                </div>
              </li>
            ))}
          </ol>
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
  disabled,
  onSubmit,
}: {
  action: LegalAction;
  pot: number;
  committed: number;
  disabled: boolean;
  onSubmit: (amount: number) => void;
}) {
  const min = action.min_amount_to ?? 0;
  const max = action.max_amount_to ?? min;
  const clamp = (value: number) => Math.max(min, Math.min(max, Math.round(value)));
  const [amount, setAmount] = useState(min);
  const presets = [
    ["Min", min],
    ["½ pot", committed + pot / 2],
    ["Pot", committed + pot],
    ["All in", max],
  ] as const;

  return (
    <div className={styles.raiseControl}>
      <div className={styles.raiseTopline}>
        <span>Raise to</span>
        <input
          aria-label="Raise amount"
          disabled={disabled}
          max={max}
          min={min}
          onChange={(event) => setAmount(clamp(Number(event.target.value)))}
          step={1}
          type="number"
          value={amount}
        />
      </div>
      <input
        aria-label="Raise amount slider"
        className={styles.raiseSlider}
        disabled={disabled}
        max={max}
        min={min}
        onChange={(event) => setAmount(Number(event.target.value))}
        step={1}
        type="range"
        value={amount}
      />
      <div className={styles.raiseBottom}>
        <div className={styles.presets}>
          {presets.map(([label, value]) => (
            <button disabled={disabled} key={label} onClick={() => setAmount(clamp(value))} type="button">
              {label}
            </button>
          ))}
        </div>
        <button className={styles.raiseButton} disabled={disabled} onClick={() => onSubmit(amount)} type="button">
          Raise <span>{formatChips(amount)}</span>
        </button>
      </div>
    </div>
  );
}
