import { useEffect, type Dispatch, type SetStateAction } from "react";

import { ApiError, api, ensureAuth } from "@/platform/http/api";
import type { AuthSession, RuntimeModelProfile, UserSettings } from "@/shared/types";
import { resolveWorkspaceId } from "@/shared/utils/workspace";

import { DEFAULT_SETTINGS } from "./constants";

interface BootstrapOptions {
  authRevision: number;
  loadSessions: () => Promise<unknown>;
  initializeSettings: (settings: UserSettings) => void;
  setModelProfiles: Dispatch<SetStateAction<Record<string, RuntimeModelProfile>>>;
  setWorkspaceId: Dispatch<SetStateAction<string>>;
  setAuthSession: Dispatch<SetStateAction<AuthSession | null>>;
  setBootStatus: Dispatch<SetStateAction<"loading" | "ready" | "unauthenticated" | "error">>;
  setError: Dispatch<SetStateAction<string>>;
}

export function useWorkspaceBootstrap({
  authRevision,
  loadSessions,
  initializeSettings,
  setModelProfiles,
  setWorkspaceId,
  setAuthSession,
  setBootStatus,
  setError,
}: BootstrapOptions) {
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const auth = await ensureAuth();
        const [, settingsResponse] = await Promise.all([loadSessions(), api.getSettings()]);
        if (cancelled) return;
        const loadedSettings = {
          ...DEFAULT_SETTINGS,
          model_profile: settingsResponse.runtime.default_model_profile,
          ...(settingsResponse.preferences.settings ?? {}),
        };
        initializeSettings(loadedSettings);
        setModelProfiles(settingsResponse.runtime.model_profiles);
        setWorkspaceId(resolveWorkspaceId(auth, loadedSettings));
        setAuthSession(auth);
        setBootStatus("ready");
      } catch (reason) {
        if (cancelled) return;
        if (reason instanceof ApiError && reason.status === 401) {
          setBootStatus("unauthenticated");
          return;
        }
        setError(reason instanceof Error ? reason.message : String(reason));
        setBootStatus("error");
      }
    })();
    return () => { cancelled = true; };
  }, [authRevision, initializeSettings, loadSessions, setAuthSession, setBootStatus, setError, setModelProfiles, setWorkspaceId]);
}
