import type { AuthSession, SessionSummary, TurnRecord, UserSettings } from "./types";

const API_ROOT = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message);
  }
}

let csrfToken = "";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({})) as { detail?: string; title?: string; code?: string };
    throw new ApiError(problem.detail ?? problem.title ?? `HTTP ${response.status}`, response.status, problem.code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function ensureAuth(): Promise<AuthSession> {
  try {
    const session = await request<AuthSession>("/auth/session");
    csrfToken = session.csrf_token;
    return session;
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    const session = await request<AuthSession>("/auth/session", { method: "POST" });
    csrfToken = session.csrf_token;
    return session;
  }
}

export const api = {
  listSessions: () => request<{ items: SessionSummary[] }>("/sessions"),
  createSession: (workspaceId = "default") =>
    request<SessionSummary>("/sessions", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId }),
    }),
  deleteSession: (sessionId: string) =>
    request<void>(`/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
  listTurns: (sessionId: string) =>
    request<{ items: TurnRecord[] }>(`/sessions/${encodeURIComponent(sessionId)}/turns?limit=500`),
  cancelTurn: (turnId: string) =>
    request<TurnRecord>(`/chat/turns/${encodeURIComponent(turnId)}/cancel`, { method: "POST" }),
  getSettings: () => request<{ preferences: { settings?: Partial<UserSettings> } }>("/settings"),
  updateSettings: (settings: Partial<UserSettings>) =>
    request<{ settings: UserSettings }>("/settings", {
      method: "PATCH",
      body: JSON.stringify(settings),
    }),
};
