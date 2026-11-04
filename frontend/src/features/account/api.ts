import type {
  Account,
  AdminMatch,
  AdminMatchSummary,
  BotDiagnostics,
  BotProfile,
  BotToken,
  EntrantKind,
  MatchConfig,
  MatchPreview,
  MatchView,
  MyMatch,
  PasswordReset,
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
  if (typeof detail === "string") return capitalize(detail);
  if (Array.isArray(detail)) {
    const first = detail[0];
    if (first && typeof first === "object" && "msg" in first && typeof first.msg === "string") {
      return capitalize(first.msg.replace(/^Value error, /, ""));
    }
  }
  return fallback;
}

function capitalize(message: string): string {
  return message.charAt(0).toUpperCase() + message.slice(1);
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...init,
      cache: "no-store",
      credentials: "include",
      headers,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new AccountApiError("The server could not be reached. Check your connection.", 0);
  }
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
  const fallback =
    response.status === 429
      ? "Too many attempts. Wait a few minutes and try again."
      : `Request failed (${response.status})`;
  throw new AccountApiError(errorMessage(payload, fallback), response.status);
}

const post = <T>(path: string, body?: unknown) =>
  apiRequest<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

// Accounts

export const getMe = () => apiRequest<Account>("/auth/me");
export const registerAccount = (email: string, password: string) =>
  post<Account>("/auth/register", { email, password });
export const loginAccount = (email: string, password: string) =>
  post<Account>("/auth/login", { email, password });
export const logoutAccount = () => post<void>("/auth/logout");
export const changePassword = (currentPassword: string, newPassword: string) =>
  post<Account>("/auth/password", { current_password: currentPassword, new_password: newPassword });
export const listAccounts = () => apiRequest<Account[]>("/admin/accounts");
export const resetPassword = (accountId: string) =>
  post<PasswordReset>(`/admin/accounts/${encodeURIComponent(accountId)}/reset-password`);

// Bots

const botPath = (botId: string) => `/bots/${encodeURIComponent(botId)}`;
export const listBots = () => apiRequest<BotProfile[]>("/bots");
export const createBot = (name: string, ip: string, port: number) =>
  post<BotToken>("/bots", { name, ip, port });
export const updateBot = (botId: string, changes: { name?: string; ip?: string; port?: number }) =>
  apiRequest<BotProfile>(botPath(botId), { method: "PATCH", body: JSON.stringify(changes) });
export const rotateBotToken = (botId: string) => post<BotToken>(`${botPath(botId)}/rotate-token`);
export const verifyBot = (botId: string) => post<BotProfile>(`${botPath(botId)}/verify`);
export const deleteBot = (botId: string) => apiRequest<void>(botPath(botId), { method: "DELETE" });
export const getBotDiagnostics = (botId: string) =>
  apiRequest<BotDiagnostics>(`${botPath(botId)}/diagnostics`);

// Matches

const matchPath = (matchId: string) => `/matches/${encodeURIComponent(matchId)}`;
export const previewMatch = (code: string) =>
  apiRequest<MatchPreview>(`/matches/code/${encodeURIComponent(code)}`);
export const joinMatch = (
  code: string,
  kind: EntrantKind,
  displayName: string | null,
  botProfileId: string | null,
) =>
  post<MatchView>("/matches/join", {
    code,
    kind,
    ...(displayName ? { display_name: displayName } : {}),
    ...(botProfileId ? { bot_profile_id: botProfileId } : {}),
  });
export const getMatch = (matchId: string, signal?: AbortSignal) =>
  apiRequest<MatchView>(matchPath(matchId), { signal });
export const leaveMatch = (matchId: string, entryId: string) =>
  apiRequest<void>(`${matchPath(matchId)}/entries/${encodeURIComponent(entryId)}`, {
    method: "DELETE",
  });
export const myMatches = () => apiRequest<MyMatch[]>("/me/matches");

// Admin matches

const adminMatchPath = (matchId: string) => `/admin/matches/${encodeURIComponent(matchId)}`;
export const createMatch = (name: string, config: MatchConfig) =>
  post<AdminMatch>("/admin/matches", { name, config });
export const listAdminMatches = () => apiRequest<AdminMatchSummary[]>("/admin/matches");
export const getAdminMatch = (matchId: string, signal?: AbortSignal) =>
  apiRequest<AdminMatch>(adminMatchPath(matchId), { signal });
export type AdminCommand = "pause" | "resume" | "end" | "cancel";
export const startMatch = (matchId: string, force = false) =>
  post<AdminMatch>(`${adminMatchPath(matchId)}/start${force ? "?force=true" : ""}`);
export const runMatchCommand = (matchId: string, command: AdminCommand) =>
  post<AdminMatch>(`${adminMatchPath(matchId)}/${command}`);
export const regenerateCode = (matchId: string) => post<AdminMatch>(`${adminMatchPath(matchId)}/code`);
export const revokeCode = (matchId: string) =>
  apiRequest<AdminMatch>(`${adminMatchPath(matchId)}/code`, { method: "DELETE" });
export const kickEntry = (matchId: string, entryId: string) =>
  apiRequest<AdminMatch>(`${adminMatchPath(matchId)}/entries/${encodeURIComponent(entryId)}`, {
    method: "DELETE",
  });
