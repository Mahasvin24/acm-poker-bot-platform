import type { ActionSubmission, PlayerTableState, PlayerTournamentState } from "./types";

export class TableApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "TableApiError";
  }
}

async function readResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return (await response.json()) as T;
  }

  let message = `Request failed (${response.status})`;
  let code: string | undefined;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") message = payload.detail;
    if (payload.detail && typeof payload.detail === "object") {
      if ("message" in payload.detail && typeof payload.detail.message === "string") {
        message = payload.detail.message;
      }
      if ("code" in payload.detail && typeof payload.detail.code === "string") {
        code = payload.detail.code;
      }
    }
  } catch {
    // Keep the status-based fallback when the API does not return JSON.
  }
  throw new TableApiError(message, response.status, code);
}

function tablePath(tournamentId: string): string {
  return `/api/v1/tournaments/${encodeURIComponent(tournamentId)}/table`;
}

export async function getPlayerTournamentState(
  tournamentId: string,
  signal?: AbortSignal,
): Promise<PlayerTournamentState> {
  const response = await fetch(`/api/v1/tournaments/${encodeURIComponent(tournamentId)}/player-status`, {
    cache: "no-store",
    credentials: "include",
    headers: { Accept: "application/json" },
    signal,
  });
  return readResponse(response);
}

export async function getTableState(
  tournamentId: string,
  signal?: AbortSignal,
): Promise<PlayerTableState> {
  const response = await fetch(tablePath(tournamentId), {
    cache: "no-store",
    credentials: "include",
    headers: { Accept: "application/json" },
    signal,
  });
  return readResponse(response);
}

export async function submitTableAction(
  tournamentId: string,
  action: ActionSubmission,
): Promise<PlayerTableState> {
  const response = await fetch(`${tablePath(tournamentId)}/action`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(action),
  });
  return readResponse(response);
}
