import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api, ensureAuth } from "@/lib/api";
import { setAppLanguage } from "@/i18n";
import { normalizeLocale } from "@/i18n/config";
import {
  deriveTitle,
  extractConcepts,
  loadLearningPreferences,
  mergeSessionMeta,
  saveLearningPreferences,
  stripLearningContext,
} from "@/lib/learning-preferences";
import type {
  ActivityItem,
  AuthSession,
  ChatMessage,
  LearningContext,
  LearningCategory,
  LearningPreferences,
  ServerEvent,
  SessionLearningMeta,
  SessionSummary,
  TurnRecord,
  UserSettings,
} from "@/lib/types";
import { StudentSocket } from "@/lib/websocket-client";
import { resolveWorkspaceId } from "@/lib/workspace";
import { createUuid } from "@/lib/uuid";

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
      startedAt: turn.started_at ?? undefined,
      completedAt: turn.completed_at ?? undefined,
    });
  }
  return result;
}

function eventDetail(event: ServerEvent): string | undefined {
  const payload = event.payload;
  for (const key of ["name", "tool", "node", "detail", "message", "status"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function toolDetail(event: ServerEvent): string | undefined {
  const detail = eventDetail(event);
  return detail && !["tool", "tools"].includes(detail.toLowerCase()) ? detail : undefined;
}

function activityLabel(event: ServerEvent): Pick<ActivityItem, "kind" | "label" | "status" | "detail"> | null {
  const detail = eventDetail(event);
  const readableTool = toolDetail(event);
  if (event.type === "tool.started") return { kind: "tool", label: "正在使用工具", status: "running", detail: readableTool };
  if (event.type === "tool.progress") return { kind: "tool", label: "工具正在处理", status: "running", detail: readableTool };
  if (event.type === "tool.completed") return { kind: "tool", label: "工具调用完成", status: "completed", detail: readableTool };
  if (event.type === "tool.error") return { kind: "tool", label: "工具执行失败", status: "error", detail: readableTool };
  if (event.type === "worker.started") return { kind: "worker", label: "教学助手正在分解问题", status: "running", detail };
  if (event.type === "worker.progress") return { kind: "worker", label: "教学助手正在协作", status: "running", detail };
  if (event.type === "worker.completed") return { kind: "worker", label: "教学助手已完成分析", status: "completed", detail };
  if (event.type === "worker.error") return { kind: "worker", label: "教学助手未能完成任务", status: "error", detail };
  if (event.type === "stream.gap") return { kind: "recovery", label: "部分实时过程已过期，已从最终记录恢复", status: "completed" };
  return null;
}

export function useStudentWorkspace() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [workspaceId, setWorkspaceId] = useState("default");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [preferences, setPreferences] = useState<LearningPreferences>(() => loadLearningPreferences());
  const preferencesRef = useRef(preferences);
  const [settings, setSettings] = useState<UserSettings>(DEFAULT_SETTINGS);
  const [authSession, setAuthSession] = useState<AuthSession | null>(null);
  const confirmedSettingsRef = useRef(settings);
  const pendingSettingsPatches = useRef<Array<{ id: number; patch: Partial<UserSettings> }>>([]);
  const nextSettingsMutation = useRef(0);
  const settingsSaveQueue = useRef<Promise<void>>(Promise.resolve());
  const [settingsError, setSettingsError] = useState("");
  const settingsErrorMutation = useRef(0);
  const [bootStatus, setBootStatus] = useState<"loading" | "ready" | "unauthenticated" | "error">("loading");
  const [authRevision, setAuthRevision] = useState(0);
  const [error, setError] = useState("");
  const [requestError, setRequestError] = useState("");
  const [socketStatus, setSocketStatus] = useState<"connecting" | "connected" | "reconnecting" | "offline">("connecting");
  const [loadingMessages, setLoadingMessages] = useState(false);
  const activeSessionRef = useRef<string | null>(null);
  const socketRef = useRef<StudentSocket | null>(null);
  const pendingRequests = useRef(new Map<string, string>());
  const inFlightTurnIds = useRef(new Set<string>());
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

  const loadTurns = useCallback(async (sessionId: string) => {
    const generation = ++loadGeneration.current;
    setLoadingMessages(true);
    try {
      const response = await api.listTurns(sessionId);
      if (generation !== loadGeneration.current || activeSessionRef.current !== sessionId) return;
      const turns = [...response.items].reverse();
      const restored = turns.flatMap(turnMessages);
      const restoredTurnIds = new Set(turns.map((turn) => turn.turn_id));
      for (const turnId of restoredTurnIds) inFlightTurnIds.current.delete(turnId);
      // A newly-created session can finish its initial history request after
      // send() has optimistically appended the first user message. Keep only
      // those request-correlated optimistic rows; stale rows from another
      // session are deliberately discarded.
      setMessages((current) => [
        ...restored,
        ...current.filter((message) => inFlightTurnIds.current.has(message.turnId) && !restoredTurnIds.has(message.turnId)),
      ]);
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
    if (!event || typeof event.type !== "string" || !event.type) return;
    if (!event.payload || typeof event.payload !== "object" || Array.isArray(event.payload)) event = { ...event, payload: {} };
    if (event.type === "command.error") {
      // Older gateways may omit request_id.  If exactly one request is pending,
      // the error is still unambiguous and its optimistic message must not linger.
      const requestId = event.request_id ?? (
        pendingRequests.current.size === 1
          ? pendingRequests.current.keys().next().value
          : undefined
      );
      if (requestId) {
        const optimisticId = pendingRequests.current.get(requestId);
        if (optimisticId) setMessages((current) => current.filter((message) => message.id !== optimisticId));
        pendingRequests.current.delete(requestId);
        inFlightTurnIds.current.delete(requestId);
      }
      if (event.payload.code === "not_found" && event.session_id) {
        const sessionId = event.session_id;
        socketRef.current?.setSession(null);
        pendingRequests.current.clear();
        inFlightTurnIds.current.clear();
        if (activeSessionRef.current === sessionId) {
          setActiveSessionId(null);
          setMessages([]);
        }
        persistPreferences((current) => {
          const sessions = { ...current.sessions };
          delete sessions[sessionId];
          return { ...current, sessions };
        });
        void loadSessions();
        return;
      }
      setRequestError(typeof event.payload.message === "string" ? event.payload.message : "请求未能提交，请稍后重试。");
      return;
    }
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
          startedAt: event.type === "chat.started" ? event.timestamp : undefined,
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
      if (event.type === "chat.started") {
        message.status = "running";
        message.startedAt ??= event.timestamp;
      }
      if (event.type === "chat.message.completed" || event.type === "chat.completed") {
        const final = typeof event.payload.content === "string" ? event.payload.content : "";
        if (final) message.content = final;
        message.status = "completed";
        message.completedAt = event.timestamp;
      }
      if (event.type === "chat.cancelled") {
        message.status = "cancelled";
        message.completedAt = event.timestamp;
      }
      if (event.type === "chat.error") {
        message.status = "failed";
        message.completedAt = event.timestamp;
      }
      const activity = activityLabel(event);
      if (activity) {
        const key = activity.kind === "tool" && activity.detail ? `tool:${activity.detail}` : activity.kind;
        const existing = message.activities.findIndex((item) => item.id === key);
        const previous = existing >= 0 ? message.activities[existing] : undefined;
        const item: ActivityItem = {
          id: key,
          ...activity,
          startedAt: previous?.startedAt ?? event.timestamp,
          ...(activity.status === "running" ? {} : { completedAt: event.timestamp }),
        };
        if (existing >= 0) message.activities[existing] = item;
        else message.activities.push(item);
        message.startedAt ??= event.timestamp;
      }
      next[index] = message;
      return next;
    });
    if (event.type === "command.ack" && event.request_id) {
      const optimisticId = pendingRequests.current.get(event.request_id);
      if (optimisticId) {
        if (event.turn_id) {
          inFlightTurnIds.current.delete(event.request_id);
          inFlightTurnIds.current.add(event.turn_id);
        }
        setMessages((current) => current.map((message) =>
          message.id === optimisticId ? { ...message, turnId: event.turn_id ?? message.turnId } : message
        ));
        pendingRequests.current.delete(event.request_id);
      }
    }
  }, [loadSessions, loadTurns, persistPreferences, updateSessionMeta]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const auth = await ensureAuth();
        const [, settingsResponse] = await Promise.all([loadSessions(), api.getSettings()]);
        if (cancelled) return;
        const loadedSettings = { ...DEFAULT_SETTINGS, ...(settingsResponse.preferences.settings ?? {}) };
        confirmedSettingsRef.current = loadedSettings;
        setSettings(loadedSettings);
        setWorkspaceId(resolveWorkspaceId(auth, loadedSettings));
        setAuthSession(auth);
        // Match nanobot's home behavior: boot into a clean composer instead of
        // forcing the most recent transcript open. History remains in Sidebar.
        setBootStatus("ready");
      } catch (reason) {
        if (!cancelled) {
          if (reason instanceof ApiError && reason.status === 401) {
            setBootStatus("unauthenticated");
            return;
          }
          setError(reason instanceof Error ? reason.message : String(reason));
          setBootStatus("error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [authRevision, loadSessions]);

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
    void setAppLanguage(normalizeLocale(settings.locale));
    const media = matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      const dark = settings.theme === "dark" || (settings.theme === "system" && media.matches);
      root.classList.toggle("dark", dark);
    };
    applyTheme();
    if (settings.theme !== "system") return;
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [settings.locale, settings.theme]);

  const createSession = useCallback(() => {
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

  const send = useCallback(async (content: string) => {
    setRequestError("");
    // Register before awaiting session creation so an early command.error can
    // still cancel this submission instead of leaving a later optimistic echo.
    const requestId = createUuid();
    inFlightTurnIds.current.add(requestId);
    pendingRequests.current.set(requestId, "");
    let sessionId = activeSessionRef.current;
    if (!sessionId) sessionId = await createSession();
    if (!pendingRequests.current.has(requestId)) return;
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
      updateSessionMeta(sessionId, { title: deriveTitle(content), topic: preferences.context.topic_name });
    }
    socketRef.current?.setSession(sessionId);
    socketRef.current?.sendChat(sessionId, content.trim(), requestId, preferences.context);
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

  const addCategory = useCallback((name: string) => {
    const category: LearningCategory = { id: createUuid(), name: name.trim(), createdAt: Date.now() };
    persistPreferences((current) => ({ ...current, categories: [...current.categories, category] }));
    return category.id;
  }, [persistPreferences]);

  const renameCategory = useCallback((categoryId: string, name: string) => {
    persistPreferences((current) => ({
      ...current,
      categories: current.categories.map((category) => category.id === categoryId ? { ...category, name: name.trim() } : category),
    }));
  }, [persistPreferences]);

  const deleteCategory = useCallback((categoryId: string) => {
    persistPreferences((current) => {
      const sessions = Object.fromEntries(Object.entries(current.sessions).map(([sessionId, meta]) => [
        sessionId,
        meta.categoryId === categoryId ? { ...meta, categoryId: undefined, updatedAt: Date.now() } : meta,
      ]));
      return { ...current, categories: current.categories.filter((category) => category.id !== categoryId), sessions };
    });
  }, [persistPreferences]);

  const patchSettings = useCallback(async (patch: Partial<UserSettings>) => {
    const mutation = ++nextSettingsMutation.current;
    pendingSettingsPatches.current.push({ id: mutation, patch });
    const optimistic = pendingSettingsPatches.current.reduce(
      (current, item) => ({ ...current, ...item.patch }),
      confirmedSettingsRef.current,
    );
    setSettings(optimistic);
    setSettingsError("");
    try {
      const request = settingsSaveQueue.current.then(() => api.updateSettings(patch));
      settingsSaveQueue.current = request.then(() => undefined, () => undefined);
      const response = await request;
      confirmedSettingsRef.current = response.settings;
      pendingSettingsPatches.current = pendingSettingsPatches.current.filter((item) => item.id !== mutation);
      const projected = pendingSettingsPatches.current.reduce(
        (current, item) => ({ ...current, ...item.patch }),
        confirmedSettingsRef.current,
      );
      setSettings(projected);
      if (settingsErrorMutation.current <= mutation) {
        settingsErrorMutation.current = 0;
        setSettingsError("");
      }
    } catch (reason) {
      pendingSettingsPatches.current = pendingSettingsPatches.current.filter((item) => item.id !== mutation);
      const projected = pendingSettingsPatches.current.reduce(
        (current, item) => ({ ...current, ...item.patch }),
        confirmedSettingsRef.current,
      );
      setSettings(projected);
      settingsErrorMutation.current = mutation;
      setSettingsError(`设置保存失败：${reason instanceof Error ? reason.message : String(reason)}`);
    }
  }, []);

  const activeMeta = activeSessionId ? preferences.sessions[activeSessionId] ?? {} : {};
  const isRunning = messages.some((message) => message.role === "assistant" && ["accepted", "running"].includes(message.status ?? ""));

  return {
    sessions,
    workspaceId,
    activeSessionId,
    setActiveSessionId,
    messages,
    preferences,
    activeMeta,
    settings,
    settingsError,
    bootStatus,
      error,
    requestError,
    clearRequestError: () => setRequestError(""),
    socketStatus,
    loadingMessages,
    isRunning,
    createSession,
    send,
    cancel,
    deleteSession,
    updateSessionMeta,
    setLearningContext,
    addCategory,
    renameCategory,
    deleteCategory,
    patchSettings,
    refresh: loadSessions,
    retryAuthentication: () => {
      setError("");
      setBootStatus("loading");
      setAuthRevision((current) => current + 1);
    },
    authSession,
    logout: async () => {
      await api.logout();
      socketRef.current?.close();
      setAuthSession(null);
      setSessions([]);
      setActiveSessionId(null);
      setMessages([]);
      setBootStatus("unauthenticated");
    },
  };
}
