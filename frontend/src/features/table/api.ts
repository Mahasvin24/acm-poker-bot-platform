import { AccountApiError, apiRequest } from "../account/api";
import type { ActionSubmission, PlayerTableState } from "./types";

export { AccountApiError as TableApiError };

export function getTableState(matchId: string, signal?: AbortSignal): Promise<PlayerTableState> {
  return apiRequest<PlayerTableState>(`/matches/${encodeURIComponent(matchId)}/table`, { signal });
}

export function getSpectatorState(matchId: string, signal?: AbortSignal): Promise<PlayerTableState> {
  return apiRequest<PlayerTableState>(`/admin/matches/${encodeURIComponent(matchId)}/table`, {
    signal,
  });
}

export function submitTableAction(
  matchId: string,
  action: ActionSubmission,
): Promise<PlayerTableState> {
  return apiRequest<PlayerTableState>(`/matches/${encodeURIComponent(matchId)}/table/action`, {
    method: "POST",
    body: JSON.stringify(action),
  });
}
