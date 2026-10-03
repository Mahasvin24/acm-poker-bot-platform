import type {
  Account,
  AdminCommandResult,
  AdminTournamentState,
  BotEndpointRegistration,
  Entrant,
  EntrantKind,
  TournamentConfig,
} from "./types";

export class AccountApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "AccountApiError";
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) return fallback;
  const detail = payload.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const first = detail[0];
    if (first && typeof first === "object" && "msg" in first && typeof first.msg === "string") {
      return first.msg;
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    cache: "no-store",
    credentials: "include",
    headers,
  });
  if (response.ok) {
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  throw new AccountApiError(errorMessage(payload, `Request failed (${response.status})`), response.status);
}

export function getMe(): Promise<Account> {
  return request<Account>("/auth/me");
}

export function registerAccount(email: string, password: string): Promise<Account> {
  return request<Account>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function loginAccount(email: string, password: string): Promise<Account> {
  return request<Account>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logoutAccount(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

function entrantPath(tournamentId: string): string {
  return `/tournaments/${encodeURIComponent(tournamentId)}/entrant`;
}

export function getEntrant(tournamentId: string): Promise<Entrant> {
  return request<Entrant>(entrantPath(tournamentId));
}

export function registerEntrant(
  tournamentId: string,
  kind: EntrantKind,
  displayName: string,
): Promise<Entrant> {
  return request<Entrant>(entrantPath(tournamentId), {
    method: "POST",
    body: JSON.stringify({ kind, display_name: displayName }),
  });
}

export function configureBot(
  tournamentId: string,
  ip: string,
  port: number,
): Promise<BotEndpointRegistration> {
  return request<BotEndpointRegistration>(`${entrantPath(tournamentId)}/bot-endpoint`, {
    method: "PUT",
    body: JSON.stringify({ ip, port }),
  });
}

export function verifyBot(tournamentId: string): Promise<Entrant> {
  return request<Entrant>(`${entrantPath(tournamentId)}/bot-endpoint/verify`, {
    method: "POST",
  });
}

function adminPath(tournamentId: string): string {
  return `/admin/tournaments/${encodeURIComponent(tournamentId)}`;
}

export function getAdminTournament(tournamentId: string): Promise<AdminTournamentState> {
  return request<AdminTournamentState>(adminPath(tournamentId));
}

export function createTournament(tournamentId: string): Promise<AdminCommandResult> {
  return request<AdminCommandResult>("/admin/tournaments", {
    method: "POST",
    body: JSON.stringify({ tournament_id: tournamentId }),
  });
}

export function updateTournament(
  tournamentId: string,
  config: TournamentConfig,
): Promise<AdminCommandResult> {
  return request<AdminCommandResult>(adminPath(tournamentId), {
    method: "PUT",
    body: JSON.stringify({ config }),
  });
}

export function runAdminCommand(
  tournamentId: string,
  command: "open" | "seat" | "start" | "pause" | "resume" | "advance",
): Promise<AdminCommandResult> {
  return request<AdminCommandResult>(`${adminPath(tournamentId)}/${command}`, {
    method: "POST",
  });
}
