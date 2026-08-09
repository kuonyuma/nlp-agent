import type { ChatMessage, LearningPreferences, ServerEvent } from "@/shared/types";

import { createRealtimeEventHandler } from "./realtime-reducer";

describe("realtime acknowledgement reconciliation", () => {
  it("reconciles an acknowledgement that arrives after the user switches sessions", () => {
    let messages: ChatMessage[] = [];
    const pendingRequests = { current: new Map([["request-1", "request-1:user"]]) };
    const inFlightTurnIds = { current: new Set(["request-1"]) };
    const handler = createRealtimeEventHandler({
      socketRef: { current: null },
      activeSessionRef: { current: "session-2" },
      pendingRequests,
      inFlightTurnIds,
      setMessages: (update) => {
        messages = typeof update === "function" ? update(messages) : update;
      },
      setActiveSessionId: vi.fn(),
      setRequestError: vi.fn(),
      persistPreferences: vi.fn((update: (value: LearningPreferences) => LearningPreferences) => update({
        version: 2,
        context: { topic_id: null, topic_name: "", level: "beginner", mode: "explain" },
        sessions: {},
        categories: [],
      })),
      updateSessionMeta: vi.fn(),
      loadSessions: vi.fn(async () => []),
      loadTurns: vi.fn(async () => undefined),
    });
    const ack: ServerEvent = {
      v: "1",
      type: "command.ack",
      request_id: "request-1",
      session_id: "session-1",
      turn_id: "turn-1",
      timestamp: new Date().toISOString(),
      payload: { command: "chat.send" },
    };

    handler(ack);

    expect(pendingRequests.current.has("request-1")).toBe(false);
    expect(inFlightTurnIds.current.has("request-1")).toBe(false);
    expect(inFlightTurnIds.current.has("turn-1")).toBe(true);
  });
});
