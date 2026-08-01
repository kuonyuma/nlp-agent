import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { deriveTitle } from "@/platform/storage/learning-preferences";
import { StudentSocket } from "@/platform/realtime/client";
import type { ChatMessage, LearningPreferences, SessionLearningMeta } from "@/shared/types";
import { createUuid } from "@/shared/utils/uuid";

interface TurnSenderOptions {
  activeSessionRef: MutableRefObject<string | null>;
  socketRef: MutableRefObject<StudentSocket | null>;
  pendingRequests: MutableRefObject<Map<string, string>>;
  inFlightTurnIds: MutableRefObject<Set<string>>;
  preferences: LearningPreferences;
  messages: ChatMessage[];
  createSession: () => Promise<string>;
  updateSessionMeta: (sessionId: string, patch: Partial<SessionLearningMeta>) => void;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setRequestError: Dispatch<SetStateAction<string>>;
}

export function useTurnSender({
  activeSessionRef,
  socketRef,
  pendingRequests,
  inFlightTurnIds,
  preferences,
  messages,
  createSession,
  updateSessionMeta,
  setMessages,
  setRequestError,
}: TurnSenderOptions) {
  const send = useCallback(async (content: string) => {
    setRequestError("");
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
  }, [activeSessionRef, createSession, inFlightTurnIds, pendingRequests, preferences.context, preferences.sessions, setMessages, setRequestError, socketRef, updateSessionMeta]);

  const cancel = useCallback(() => {
    const running = [...messages].reverse().find((message) => message.role === "assistant" && ["accepted", "running"].includes(message.status ?? ""));
    if (running) socketRef.current?.cancel(running.turnId);
  }, [messages, socketRef]);

  return { send, cancel };
}
