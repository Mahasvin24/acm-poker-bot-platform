import Link from "next/link";

import styles from "./poker-table.module.css";
import type { PlayerTournamentState } from "./types";

export function TournamentResults({
  result,
  error,
  signInRequired,
  onRetry,
}: {
  result: PlayerTournamentState;
  error: string | null;
  signInRequired: boolean;
  onRetry: () => void;
}) {
  const completed = result.status === "completed";
  const winner = result.standings.find((standing) => standing.position === 1);

  return (
    <main className={styles.gate} id="main-content">
      <section className={`${styles.gateCard} ${styles.resultsCard}`} aria-labelledby="results-heading">
        <Link className={styles.wordmark} href="/">ACM / POKER</Link>
        <p className={styles.kicker}>{result.tournament_id}</p>
        <h1 id="results-heading" aria-live="polite">
          {completed ? "Tournament complete" : "You've been eliminated"}
        </h1>
        <p>
          {result.placement !== null ? <>Your final placement: <strong>#{result.placement}</strong>.</> : "Your final placement is not available yet."}
          {result.placement === 1 && completed && " Congratulations—you won the tournament!"}
        </p>
        {completed ? (
          <>
            <p>{winner ? <>Winner: <strong>{winner.display_name}</strong>.</> : "The winner has not been recorded."}</p>
            {result.standings.length > 0 ? (
              <table className={styles.standings}>
                <caption>Final standings · equal positions indicate a tie</caption>
                <thead><tr><th scope="col">Place</th><th scope="col">Player</th></tr></thead>
                <tbody>
                  {result.standings.map((standing) => (
                    <tr key={standing.entrant_id} data-viewer={standing.entrant_id === result.entrant_id}>
                      <td>#{standing.position}</td>
                      <th scope="row">{standing.display_name}{standing.entrant_id === result.entrant_id && " (You)"}</th>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : <p>Final standings are not available yet.</p>}
          </>
        ) : <p>The tournament is still in progress. This page will show the final standings automatically when it finishes.</p>}
        {error && <p role="alert">Could not refresh tournament status: {error}</p>}
        <div className={styles.gateActions}>
          {error && (signInRequired
            ? <Link href={`/account?tournament=${encodeURIComponent(result.tournament_id)}`}>Sign In</Link>
            : <button type="button" onClick={onRetry}>Try Again</button>)}
          <Link href={`/dashboard?tournament=${encodeURIComponent(result.tournament_id)}`}>My Dashboard</Link>
          <Link href="/play">Change tournament</Link>
        </div>
      </section>
    </main>
  );
}
