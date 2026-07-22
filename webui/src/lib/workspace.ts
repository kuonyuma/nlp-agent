import type { AuthSession, UserSettings } from "./types";

export function resolveWorkspaceId(auth: Pick<AuthSession, "workspace_ids">, settings: Partial<UserSettings> = {}): string {
  const authorized = Array.isArray(auth.workspace_ids) ? auth.workspace_ids : [];
  const preferred = settings.default_workspace_id;
  if (preferred && authorized.includes(preferred)) return preferred;
  return authorized[0] ?? "default";
}
