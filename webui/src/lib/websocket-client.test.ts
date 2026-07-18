import { StudentSocket } from "./websocket-client";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public readonly url: string) {}
  open() { this.readyState = FakeWebSocket.OPEN; this.onopen?.(); }
  send(value: string) { this.sent.push(value); }
  close() { this.readyState = FakeWebSocket.CLOSED; }
}

describe("StudentSocket", () => {
  it("uses the versioned backend command envelope and session subscription", () => {
    const instances: FakeWebSocket[] = [];
    vi.stubGlobal("WebSocket", class extends FakeWebSocket {
      constructor(url: string) { super(url); instances.push(this); }
    });
    const client = new StudentSocket(vi.fn(), vi.fn());
    client.setSession("session_1");
    const instance = instances[0];
    instance.open();
    expect(instance.sent).toEqual([]);
    instance.onmessage?.({ data: JSON.stringify({ v: "1", type: "connection.ready", timestamp: new Date().toISOString(), payload: {} }) });
    client.sendChat("session_1", "hello", "request_1");

    const frames = instance.sent.map((value) => JSON.parse(value) as { type: string; v: string; payload: Record<string, unknown> });
    expect(frames[0]).toMatchObject({ v: "1", type: "session.subscribe", payload: { session_id: "session_1" } });
    expect(frames[1]).toMatchObject({ v: "1", type: "chat.send", payload: { session_id: "session_1", content: "hello", idempotency_key: "request_1" } });
    client.close();
    vi.unstubAllGlobals();
  });
});
