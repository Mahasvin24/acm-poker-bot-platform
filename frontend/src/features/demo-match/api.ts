import type { ActionSubmission, PlayerTableState } from "../table/types";

export type DemoResult = "human_win" | "bot_win" | "tie";

export interface DemoMatchState {
  status: "idle" | "active" | "completed";
  match_id: string | null;
  result: DemoResult | null;
  table: PlayerTableState | null;
}

export class DemoApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "DemoApiError";
  }
}

const basePath = "/api/v1/demo-human-versus-bot";

async function readResponse(response: Response): Promise<DemoMatchState> {
  if (response.ok) return (await response.json()) as DemoMatchState;

  let message = `Request failed (${response.status})`;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") message = payload.detail;
  } catch {
    // Retain the status-based message when the server did not return JSON.
  }
  throw new DemoApiError(message, response.status);
}

export async function getDemoMatch(signal?: AbortSignal): Promise<DemoMatchState> {
  const response = await fetch(basePath, {
    cache: "no-store",
    credentials: "include",
    headers: { Accept: "application/json" },
    signal,
  });
  return readResponse(response);
}

async function post(path: string, body?: ActionSubmission): Promise<DemoMatchState> {
  const response = await fetch(`${basePath}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return readResponse(response);
}

export const startDemoMatch = () => post("/start");
export const endDemoMatch = () => post("/end");
export const submitDemoAction = (action: ActionSubmission) => post("/action", action);
export const forceDemoResult = (result: "human_win" | "bot_win") =>
  post(`/cheat/${result}`);
