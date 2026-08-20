import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { api } from "@/platform/http/api";
import {
  extractConcepts,
  stripLearningContext,
} from "@/platform/storage/learning-preferences";
import { StudentSocket } from "@/platform/realtime/client";
import type { ChatMessage, LearningPreferences, SessionLearningMeta, TurnRecord } from "@/shared/types";

export function turnMessages(turn: TurnRecord): ChatMessage[] {
  const createdAt = turn.created_at;
  const result: ChatMessage[] = [{
    id: `${turn.turn_id}:user`,
    turnId: turn.turn_id,
    role: "user",
    content: stripLearningContext(turn.input_text),
    createdAt,
  }];
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

interface TurnHistoryOptions {
  activeSessionRef: MutableRefObject<string | null>;
  socketRef: MutableRefObject<StudentSocket | null>;
  preferencesRef: MutableRefObject<LearningPreferences>;
  inFlightTurnIds: MutableRefObject<Set<string>>;
  loadGenerationRef: MutableRefObject<number>;
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setLoadingMessages: Dispatch<SetStateAction<boolean>>;
  updateSessionMeta: (sessionId: string, patch: Partial<SessionLearningMeta>) => void;
}

export function useTurnHistory({
  activeSessionRef,
  socketRef,
  preferencesRef,
  inFlightTurnIds,
  loadGenerationRef,
  setMessages,
  setLoadingMessages,
  updateSessionMeta,
}: TurnHistoryOptions) {
  return useCallback(async (sessionId: string) => {
    const generation = ++loadGenerationRef.current;
    setLoadingMessages(true);
    try {
      const response = await api.listTurns(sessionId);
      if (generation !== loadGenerationRef.current || activeSessionRef.current !== sessionId) return;
      const turns = [...response.items].reverse();
      const restored = turns.flatMap(turnMessages);
      const restoredTurnIds = new Set(turns.map((turn) => turn.turn_id));
      for (const turnId of restoredTurnIds) inFlightTurnIds.current.delete(turnId);
      setMessages((current) => [
        ...restored,
        ...current.filter((message) => inFlightTurnIds.current.has(message.turnId) && !restoredTurnIds.has(message.turnId)),
      ]);
      const first = turns[0];
      const lastAnswer = [...turns].reverse().find((turn) => turn.final_text)?.final_text;
      if (first) {
        const stored = preferencesRef.current.sessions[sessionId];
        updateSessionMeta(sessionId, {
          summary: lastAnswer?.replace(/[#*_`]/g, "").slice(0, 180),
          concepts: lastAnswer ? extractConcepts(lastAnswer) : stored?.concepts,
        });
      }
      for (const turn of turns) {
        if (["accepted", "running"].includes(turn.status)) socketRef.current?.resume(turn.turn_id, 0);
      }
    } finally {
      if (generation === loadGenerationRef.current) setLoadingMessages(false);
    }
  }, [activeSessionRef, inFlightTurnIds, loadGenerationRef, preferencesRef, setLoadingMessages, setMessages, socketRef, updateSessionMeta]);
}
