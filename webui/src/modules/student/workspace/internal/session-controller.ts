import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";

import { api } from "@/platform/http/api";
import type { LearningPreferences, SessionLearningMeta, SessionSummary } from "@/shared/types";

interface SessionControllerOptions {
  preferences: LearningPreferences;
  persistPreferences: (update: (current: LearningPreferences) => LearningPreferences) => void;
  updateSessionMeta: (sessionId: string, patch: Partial<SessionLearningMeta>) => void;
}

export function useSessionController({ preferences, persistPreferences, updateSessionMeta }: SessionControllerOptions) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("default");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const activeSessionRef = useRef<string | null>(null);
  const creationRef = useRef<Promise<string> | null>(null);

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
  }, [activeSessionId]);

  const loadSessions = useCallback(async () => {
    const response = await api.listSessions();
    setSessions(response.items);
    const existing = new Set(response.items.map((session) => session.session_id));
    persistPreferences((current) => {
      const sessions = Object.fromEntries(
        Object.entries(current.sessions).filter(([sessionId]) => existing.has(sessionId)),
      );
      return Object.keys(sessions).length === Object.keys(current.sessions).length
        ? current
        : { ...current, sessions };
    });
    return response.items;
  }, [persistPreferences]);

  const createBackendSession = useCallback(() => {
    if (creationRef.current) return creationRef.current;
    const creation = (async () => {
      const session = await api.createSession(workspaceId);
      setSessions((current) => current.some((item) => item.session_id === session.session_id) ? current : [session, ...current]);
      updateSessionMeta(session.session_id, { topic: preferences.context.topic_name, title: "新的学习对话" });
      setActiveSessionId(session.session_id);
      return session.session_id;
    })();
    creationRef.current = creation;
    void creation.then(
      () => { creationRef.current = null; },
      () => { creationRef.current = null; },
    );
    return creation;
  }, [preferences.context.topic_name, updateSessionMeta, workspaceId]);

  const startNewChat = useCallback(() => {
    setActiveSessionId(null);
  }, []);

  const deleteSession = useCallback(async (sessionId: string) => {
    await api.deleteSession(sessionId);
    const remaining = sessions.filter((session) => session.session_id !== sessionId);
    setSessions(remaining);
    persistPreferences((current) => {
      const nextSessions = { ...current.sessions };
      delete nextSessions[sessionId];
      return { ...current, sessions: nextSessions };
    });
    if (activeSessionRef.current === sessionId) setActiveSessionId(remaining[0]?.session_id ?? null);
  }, [persistPreferences, sessions]);

  return {
    sessions,
    setSessions,
    workspaceId,
    setWorkspaceId,
    activeSessionId,
    setActiveSessionId,
    activeSessionRef: activeSessionRef as MutableRefObject<string | null>,
    loadSessions,
    createBackendSession,
    startNewChat,
    deleteSession,
  };
}
