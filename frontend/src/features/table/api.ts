import type { ActionSubmission, PlayerTableState } from "./types";

export class TableApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "TableApiError";
  }
}

async function readResponse(response: Response): Promise<PlayerTableState> {
  if (response.ok) {
    return (await response.json()) as PlayerTableState;
  }

  let message = `Request failed (${response.status})`;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") message = payload.detail;
  } catch {
    // Keep the status-based fallback when the API does not return JSON.
  }
  throw new TableApiError(message, response.status);
}

function tablePath(tournamentId: string): string {
  return `/api/v1/tournaments/${encodeURIComponent(tournamentId)}/table`;
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
