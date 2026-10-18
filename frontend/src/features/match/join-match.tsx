"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { AccountApiError, joinMatch, listBots, previewMatch } from "../account/api";
import styles from "../account/account.module.css";
import type { BotProfile, EntrantKind, MatchPreview } from "../account/types";
import { useAccount } from "../account/use-account";
import { formatConfig } from "./format";

const CODE_PATTERN = /^[23456789ABCDEFGHJKMNPQRSTVWXYZ]{6}$/;

export function normalizeCode(value: string): string {
  return value.replace(/[\s-]+/g, "").toUpperCase();
}

export function formatCode(value: string): string {
  const code = normalizeCode(value);
  return code.length > 3 ? `${code.slice(0, 3)}-${code.slice(3, 6)}` : code;
}

export function CodeEntry({ initialCode = "", compact = false }: { initialCode?: string; compact?: boolean }) {
  const router = useRouter();
  const [code, setCode] = useState(formatCode(initialCode));
  const [error, setError] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = normalizeCode(code);
    if (!CODE_PATTERN.test(normalized)) {
      setError("Codes are six letters and digits, like K7Q-4PM. They never use 0, 1, I, L, O, or U.");
      return;
    }
    setError(null);
    router.push(`/join/${normalized}`);
  };

  return (
    <form className={styles.form} onSubmit={submit} style={compact ? { marginTop: 18 } : undefined}>
      <div className={styles.field}>
        <label htmlFor="join-code">Match code</label>
        <input
          aria-describedby={error ? "join-code-error" : "join-code-hint"}
          aria-invalid={Boolean(error)}
          autoCapitalize="characters"
          autoComplete="off"
          className={styles.codeInput}
          id="join-code"
          inputMode="text"
          maxLength={7}
          name="code"
          onChange={(event) => {
            setCode(formatCode(event.target.value));
            if (error) setError(null);
          }}
          placeholder="K7Q-4PM"
          spellCheck={false}
          value={code}
        />
        {error
          ? <p className={styles.fieldError} id="join-code-error" role="alert">{error}</p>
          : <p className={styles.fieldHint} id="join-code-hint">Ask the organizer for the code shown on their screen.</p>}
      </div>
      <button className={styles.primaryButton} type="submit">Find Match →</button>
    </form>
  );
}

export function JoinMatch({ code }: { code: string }) {
  const router = useRouter();
  const normalized = normalizeCode(code);
  const { account, error: accountError } = useAccount(`/join/${normalized}`);
  const [preview, setPreview] = useState<MatchPreview | null>(null);
  const [bots, setBots] = useState<BotProfile[]>([]);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [kind, setKind] = useState<EntrantKind>("human");
  const [botId, setBotId] = useState<string>("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!account) return;
    let active = true;
    Promise.all([previewMatch(normalized), listBots()])
      .then(([match, ownBots]) => {
        if (!active) return;
        setPreview(match);
        setBots(ownBots);
        const ready = ownBots.find((bot) => bot.verified_at);
        if (ready) setBotId(ready.id);
      })
      .catch((reason: unknown) => {
        if (active) setLookupError(reason instanceof Error ? reason.message : "That code could not be checked.");
      });
    return () => {
      active = false;
    };
  }, [account, normalized]);

  const join = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const joined = await joinMatch(
        normalized,
        kind,
        kind === "human" ? displayName.trim() : displayName.trim() || null,
        kind === "bot" ? botId : null,
      );
      router.push(`/match/${joined.match_id}`);
    } catch (reason) {
      setError(reason instanceof AccountApiError ? reason.message : "Joining failed. Try again.");
      setBusy(false);
    }
  };

  const readyBots = bots.filter((bot) => bot.verified_at);

  return (
    <main className={styles.page} id="main-content">
      <header className={styles.header}>
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <span className={styles.headerTitle}>Join Match</span>
        <div className={styles.headerAccount}>
          {account && <span>{account.email}</span>}
          <Link className={styles.textButton} href="/dashboard">Dashboard</Link>
        </div>
      </header>
      <div className={styles.narrow}>
        {accountError || lookupError ? (
          <section className={styles.panel}>
            <p className={styles.sectionLabel}>Code {formatCode(normalized)}</p>
            <h2>We couldn’t open that match.</h2>
            <p className={styles.panelIntro}>{lookupError ?? accountError}</p>
            <CodeEntry compact />
          </section>
        ) : !preview ? (
          <div className={styles.loading}><span>Checking code</span></div>
        ) : (
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <div>
                <p className={styles.sectionLabel}>Code {formatCode(normalized)}</p>
                <h2>{preview.name}</h2>
                <p className={styles.panelIntro}>{formatConfig(preview.config)}</p>
              </div>
              <span className={styles.statusPill} data-status={preview.joinable ? "lobby" : "closed"}>
                {preview.seats_taken}/{preview.max_seats} seats
              </span>
            </div>
            {!preview.joinable ? (
              <div className={styles.entrantBody}>
                <p className={styles.formError}>{preview.reason ? preview.reason.charAt(0).toUpperCase() + preview.reason.slice(1) : "This match cannot be joined."}.</p>
                <div className={styles.panelActions}>
                  <Link className={styles.secondaryButton} href="/dashboard">Back to dashboard</Link>
                </div>
              </div>
            ) : (
              <form className={styles.form} onSubmit={join}>
                <fieldset>
                  <legend className={styles.kindLegend}>Who is taking the seat?</legend>
                  <div className={styles.kindChoices}>
                    <label className={styles.kindChoice}>
                      <input checked={kind === "human"} name="kind" onChange={() => setKind("human")} type="radio" value="human" />
                      <strong>Me</strong>
                      <span>Play every decision in this browser.</span>
                    </label>
                    <label className={styles.kindChoice}>
                      <input checked={kind === "bot"} name="kind" onChange={() => setKind("bot")} type="radio" value="bot" />
                      <strong>My bot</strong>
                      <span>{readyBots.length ? "Seat one of your verified bots." : "Verify a bot under My Bots first."}</span>
                    </label>
                  </div>
                </fieldset>
                {kind === "bot" && (
                  readyBots.length ? (
                    <div className={styles.field}>
                      <label htmlFor="join-bot">Bot</label>
                      <select id="join-bot" onChange={(event) => setBotId(event.target.value)} value={botId}>
                        {readyBots.map((bot) => <option key={bot.id} value={bot.id}>{bot.name} · {bot.ip}:{bot.port}</option>)}
                      </select>
                    </div>
                  ) : (
                    <p className={styles.formError}>
                      You have no verified bots. <Link href="/dashboard#bots">Add and verify one</Link>, then come back to this code.
                    </p>
                  )
                )}
                <div className={styles.field}>
                  <label htmlFor="join-name">{kind === "human" ? "Name at the table" : "Seat name (optional)"}</label>
                  <input
                    autoComplete="nickname"
                    id="join-name"
                    maxLength={80}
                    onChange={(event) => setDisplayName(event.target.value)}
                    placeholder={kind === "human" ? "e.g. Maya" : readyBots.find((bot) => bot.id === botId)?.name ?? "Uses the bot's name"}
                    required={kind === "human"}
                    value={displayName}
                  />
                </div>
                {error && <p className={styles.formError} role="alert">{error}</p>}
                <button
                  className={styles.primaryButton}
                  disabled={busy || (kind === "bot" && !readyBots.length)}
                  type="submit"
                >
                  {busy ? "Joining…" : kind === "human" ? "Take a Seat" : "Seat My Bot"}
                </button>
              </form>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
