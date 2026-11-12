"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import styles from "../account/account.module.css";
import { useAccount } from "../account/use-account";
import { PokerTable } from "./poker-table";

export function SpectatorView({ matchId, standalone = false }: { matchId: string; standalone?: boolean }) {
  const path = `/admin/match/${encodeURIComponent(matchId)}/spectator`;
  const { account, error: accountError } = useAccount(path);
  const container = useRef<HTMLElement>(null);
  const controls = useRef<HTMLDivElement>(null);
  const [reveal, setReveal] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === container.current);
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);

  useEffect(() => {
    if (!controls.current) return;
    const measure = () => {
      container.current?.style.setProperty("--spectator-controls-height", `${controls.current?.getBoundingClientRect().height ?? 0}px`);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(controls.current);
    measure();
    return () => observer.disconnect();
  }, [account]);

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await container.current?.requestFullscreen();
      setError(null);
    } catch {
      setError("Fullscreen is unavailable here. Use Open in new tab for a larger view.");
    }
  };

  if (!account || account.role !== "admin") {
    return <p role="status">{accountError ?? (account ? "An admin account is needed to spectate." : "Loading spectator view…")}</p>;
  }

  return (
    <section ref={container} className={`${standalone ? styles.page : ""} ${styles.spectatorViewer}`} aria-label="Spectator controls">
      <div ref={controls}>
        <div className={styles.spectatorToolbar}>
          <strong>Spectator view</strong>
          <label className={styles.checkRow}>
            <input checked={reveal} onChange={(event) => setReveal(event.target.checked)} type="checkbox" />
            Show cards &amp; win odds
          </label>
          <button className={styles.secondaryButton} onClick={() => void toggleFullscreen()} type="button">{fullscreen ? "Exit fullscreen" : "Fullscreen"}</button>
          <a className={styles.secondaryButton} href={path} target="_blank" rel="noopener noreferrer">Open in new tab</a>
          {standalone && <Link className={styles.textButton} href={`/admin/match/${encodeURIComponent(matchId)}`}>Back to match</Link>}
        </div>
        {reveal && <p className={styles.spectatorNote}>Estimated win odds if everyone still in the hand reaches showdown. Ties split the percentage.</p>}
        {error && <p className={styles.formError} role="alert">{error}</p>}
      </div>
      <PokerTable key={`${matchId}-${reveal ? "revealed" : "hidden"}`} embedded fullScreen={standalone || fullscreen} exitHref="/admin" matchId={matchId} mode="spectator" revealCards={reveal} />
    </section>
  );
}
