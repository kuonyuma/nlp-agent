import { useCallback, useEffect, useRef, useState } from "react";

import { api, ensureAuth } from "@/lib/api";
import {
  deriveTitle,
  encodeLearningPrompt,
  extractConcepts,
  loadLearningPreferences,
  mergeSessionMeta,
  saveLearningPreferences,
  stripLearningContext,
} from "@/lib/learning-preferences";
import type {
  ActivityItem,
  ChatMessage,
  LearningContext,
  LearningPreferences,
  ServerEvent,
  SessionLearningMeta,
  SessionSummary,
  TurnRecord,
  UserSettings,
} from "@/lib/types";
import { StudentSocket } from "@/lib/websocket-client";

const DEFAULT_SETTINGS: UserSettings = {
  locale: "zh-CN",
  theme: "system",
  show_reasoning: false,
  stream_render_interval_ms: 30,
};

function turnMessages(turn: TurnRecord): ChatMessage[] {
  const createdAt = turn.created_at;
  const result: ChatMessage[] = [
    {
      id: `${turn.turn_id}:user`,
      turnId: turn.turn_id,
      role: "user",
      content: stripLearningContext(turn.input_text),
      createdAt,
    },
  ];
  if (turn.final_text || turn.status !== "accepted") {
    result.push({
      id: `${turn.turn_id}:assistant`,
      turnId: turn.turn_id,
      role: "assistant",
      content: turn.final_text ?? "",
      status: turn.status,
      createdAt: turn.started_at ?? createdAt,
    });
  }
  return result;
}

function activityLabel(event: ServerEvent): Pick<ActivityItem, "kind" | "label" | "status"> | null {
  if (event.type === "tool.started") return { kind: "tool", label: "正在查找资料或运行示例", status: "running" };
  if (event.type === "tool.completed") return { kind: "tool", label: "资料与示例准备完成", status: "completed" };
  if (event.type === "worker.started") return { kind: "worker", label: "教学助手正在分解问题", status: "running" };
  if (event.type === "worker.progress") return { kind: "worker", label: "教学助手正在协作", status: "running" };
  if (event.type === "worker.completed") return { kind: "worker", label: "教学助手已完成分析", status: "completed" };
  if (event.type === "worker.error") return { kind: "worker", label: "教学助手未能完成任务", status: "error" };
  if (event.type === "stream.gap") return { kind: "recovery", label: "部分实时过程已过期，已从最终记录恢复", status: "completed" };
  return null;
}

export function useStudentWorkspace() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [preferences, setPreferences] = useState<LearningPreferences>(() => loadLearningPreferences());
  const preferencesRef = useRef(preferences);
  const [settings, setSettings] = useState<UserSettings>(DEFAULT_SETTINGS);
  const [bootStatus, setBootStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [socketStatus, setSocketStatus] = useState<"connecting" | "connected" | "reconnecting" | "offline">("connecting");
  const [loadingMessages, setLoadingMessages] = useState(false);
  const activeSessionRef = useRef<string | null>(null);
  const socketRef = useRef<StudentSocket | null>(null);
  const pendingRequests = useRef(new Map<string, string>());
  const loadGeneration = useRef(0);
  const creationRef = useRef<Promise<string> | null>(null);

  const persistPreferences = useCallback((update: (current: LearningPreferences) => LearningPreferences) => {
    setPreferences((current) => {
      const next = update(current);
      preferencesRef.current = next;
      saveLearningPreferences(next);
      return next;
    });
  }, []);

  const updateSessionMeta = useCallback((sessionId: string, patch: Partial<SessionLearningMeta>) => {
    persistPreferences((current) => ({
      ...current,
      sessions: {
        ...current.sessions,
        [sessionId]: mergeSessionMeta(current.sessions[sessionId], patch),
      },
    }));
  }, [persistPreferences]);

  const loadSessions = useCallback(async () => {
    const response = await api.listSessions();
    setSessions(response.items);
    return response.items;
  }, []);

  const loadTurns = useCallback(async (sessionId: string) => {
    const generation = ++loadGeneration.current;
    setLoadingMessages(true);
    try {
      const response = await api.listTurns(sessionId);
      if (generation !== loadGeneration.current || activeSessionRef.current !== sessionId) return;
      const turns = [...response.items].reverse();
      setMessages(turns.flatMap(turnMessages));
      const first = turns[0];
      const lastAnswer = [...turns].reverse().find((turn) => turn.final_text)?.final_text;
      if (first) {
        const stored = preferencesRef.current.sessions[sessionId];
        updateSessionMeta(sessionId, {
          title: stored?.title ?? deriveTitle(first.input_text),
          summary: lastAnswer?.replace(/[#*_`]/g, "").slice(0, 180),
          concepts: lastAnswer ? extractConcepts(lastAnswer) : stored?.concepts,
        });
      }
      for (const turn of turns) {
        if (["accepted", "running"].includes(turn.status)) socketRef.current?.resume(turn.turn_id, 0);
      }
    } finally {
      if (generation === loadGeneration.current) setLoadingMessages(false);
    }
  }, [updateSessionMeta]);

  const applyEvent = useCallback((event: ServerEvent) => {
    if (event.type === "session.created" || event.type === "session.deleted" || event.type === "session.updated") {
      void loadSessions();
    }
    if (!event.session_id || event.session_id !== activeSessionRef.current || !event.turn_id) return;
    if (event.type === "stream.gap") {
      void loadTurns(event.session_id);
    }
    if (event.type === "chat.completed" && typeof event.payload.content === "string") {
      updateSessionMeta(event.session_id, {
        summary: event.payload.content.replace(/[#*_`]/g, "").slice(0, 180),
        concepts: extractConcepts(event.payload.content),
      });
    }
    setMessages((current) => {
      const next = [...current];
      const assistantId = `${event.turn_id}:assistant`;
      let index = next.findIndex((message) => message.id === assistantId);
      const ensureAssistant = () => {
        if (index >= 0) return;
        next.push({
          id: assistantId,
          turnId: event.turn_id!,
          role: "assistant",
          content: "",
          status: "running",
          activities: [],
          createdAt: event.timestamp,
        });
        index = next.length - 1;
      };
      if (event.type.startsWith("chat.") || event.type.startsWith("tool.") || event.type.startsWith("worker.") || event.type === "stream.gap") {
        ensureAssistant();
      }
      if (index < 0) return next;
      const message = { ...next[index], activities: [...(next[index].activities ?? [])] };
      const delta = typeof event.payload.delta === "string" ? event.payload.delta : "";
      if (event.type === "chat.delta") message.content += delta;
      if (event.type === "chat.reasoning.delta") message.reasoning = `${message.reasoning ?? ""}${delta}`;
      if (event.type === "chat.started") message.status = "running";
      if (event.type === "chat.message.completed" || event.type === "chat.completed") {
        const final = typeof event.payload.content === "string" ? event.payload.content : "";
        if (final) message.content = final;
        message.status = "completed";
      }
      if (event.type === "chat.cancelled") message.status = "cancelled";
      if (event.type === "chat.error") message.status = "failed";
      const activity = activityLabel(event);
      if (activity) {
        const key = `${activity.kind}:${activity.label}`;
        const existing = message.activities.findIndex((item) => item.id === key || item.kind === activity.kind && item.status === "running");
        const item: ActivityItem = { id: key, ...activity };
        if (existing >= 0) message.activities[existing] = item;
        else message.activities.push(item);
      }
      next[index] = message;
      return next;
    });
    if (event.type === "command.ack" && event.request_id) {
      const optimisticId = pendingRequests.current.get(event.request_id);
      if (optimisticId) {
        setMessages((current) => current.map((message) =>
          message.id === optimisticId ? { ...message, turnId: event.turn_id ?? message.turnId } : message
        ));
        pendingRequests.current.delete(event.request_id);
      }
    }
  }, [loadSessions, loadTurns, updateSessionMeta]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        await ensureAuth();
        const [, settingsResponse] = await Promise.all([loadSessions(), api.getSettings()]);
        if (cancelled) return;
        setSettings({ ...DEFAULT_SETTINGS, ...(settingsResponse.preferences.settings ?? {}) });
        // Match nanobot's home behavior: boot into a clean composer instead of
        // forcing the most recent transcript open. History remains in Sidebar.
        setBootStatus("ready");
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
          setBootStatus("error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [loadSessions]);

  useEffect(() => {
    if (bootStatus !== "ready") return;
    const socket = new StudentSocket(applyEvent, setSocketStatus);
    socketRef.current = socket;
    socket.connect();
    return () => {
      socket.close();
      socketRef.current = null;
    };
  }, [applyEvent, bootStatus]);

  useEffect(() => {
    activeSessionRef.current = activeSessionId;
    loadGeneration.current += 1;
    socketRef.current?.setSession(activeSessionId);
    queueMicrotask(() => {
      if (activeSessionId) void loadTurns(activeSessionId).catch((reason) => setError(String(reason)));
      else setMessages([]);
    });
  }, [activeSessionId, loadTurns]);

  useEffect(() => {
    const root = document.documentElement;
    root.lang = settings.locale;
    const dark = settings.theme === "dark" || (settings.theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    root.classList.toggle("dark", dark);
  }, [settings.locale, settings.theme]);

  const createSession = useCallback(() => {
    if (creationRef.current) return creationRef.current;
    const creation = (async () => {
      const session = await api.createSession();
      setSessions((current) => current.some((item) => item.session_id === session.session_id) ? current : [session, ...current]);
      updateSessionMeta(session.session_id, { topic: preferences.context.topic, title: "新的学习对话" });
      setActiveSessionId(session.session_id);
      return session.session_id;
    })();
    creationRef.current = creation;
    void creation.then(
      () => { creationRef.current = null; },
      () => { creationRef.current = null; },
    );
    return creation;
  }, [preferences.context.topic, updateSessionMeta]);

  const send = useCallback(async (content: string) => {
    let sessionId = activeSessionRef.current;
    if (!sessionId) sessionId = await createSession();
    const requestId = crypto.randomUUID();
    const optimisticId = `${requestId}:user`;
    pendingRequests.current.set(requestId, optimisticId);
    setMessages((current) => [...current, {
      id: optimisticId,
      turnId: requestId,
      role: "user",
      content: content.trim(),
      createdAt: new Date().toISOString(),
    }]);
    const currentMeta = preferences.sessions[sessionId];
    if (!currentMeta?.title || currentMeta.title === "新的学习对话") {
      updateSessionMeta(sessionId, { title: deriveTitle(content), topic: preferences.context.topic });
    }
    socketRef.current?.setSession(sessionId);
    socketRef.current?.sendChat(sessionId, encodeLearningPrompt(content, preferences.context), requestId);
  }, [createSession, preferences.context, preferences.sessions, updateSessionMeta]);

  const cancel = useCallback(() => {
    const running = [...messages].reverse().find((message) => message.role === "assistant" && ["accepted", "running"].includes(message.status ?? ""));
    if (running) socketRef.current?.cancel(running.turnId);
  }, [messages]);

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

  const setLearningContext = useCallback((context: LearningContext) => {
    persistPreferences((current) => ({ ...current, context }));
  }, [persistPreferences]);

  const patchSettings = useCallback(async (patch: Partial<UserSettings>) => {
    setSettings((current) => ({ ...current, ...patch }));
    await api.updateSettings(patch);
  }, []);

  const activeMeta = activeSessionId ? preferences.sessions[activeSessionId] ?? {} : {};
  const isRunning = messages.some((message) => message.role === "assistant" && ["accepted", "running"].includes(message.status ?? ""));

  return {
    sessions,
    activeSessionId,
    setActiveSessionId,
    messages,
    preferences,
    activeMeta,
    settings,
    bootStatus,
    error,
    socketStatus,
    loadingMessages,
    isRunning,
    createSession,
    send,
    cancel,
    deleteSession,
    updateSessionMeta,
    setLearningContext,
    patchSettings,
    refresh: loadSessions,
  };
}
