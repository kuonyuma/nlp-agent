import type { ServerEvent } from "./types";

type EventHandler = (event: ServerEvent) => void;
type StatusHandler = (status: "connecting" | "connected" | "reconnecting" | "offline") => void;

interface Command {
  v: "1";
  type: string;
  request_id: string;
  payload: Record<string, unknown>;
}

export class StudentSocket {
  private socket: WebSocket | null = null;
  private stopped = false;
  private reconnectTimer: number | null = null;
  private reconnectAttempt = 0;
  private ready = false;
  private activeSession: string | null = null;
  private readonly lastSequences = new Map<string, number>();
  private readonly pending: Command[] = [];

  constructor(
    private readonly onEvent: EventHandler,
    private readonly onStatus: StatusHandler,
  ) {}

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) return;
    this.stopped = false;
    this.onStatus(this.reconnectAttempt ? "reconnecting" : "connecting");
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    this.socket = new WebSocket(`${protocol}//${location.host}/ws/v1`);
    this.socket.onopen = () => {
      this.reconnectAttempt = 0;
      // TCP/WebSocket upgrade succeeded, but the server still has to accept
      // this connection into the Agent gateway.  Commands wait for its
      // protocol-level connection.ready frame.
      this.ready = false;
    };
    this.socket.onmessage = (message) => {
      let event: ServerEvent;
      try {
        event = JSON.parse(String(message.data)) as ServerEvent;
      } catch {
        return;
      }
      if (event.type === "connection.ready") {
        this.ready = true;
        this.onStatus("connected");
        if (this.activeSession) this.command("session.subscribe", { session_id: this.activeSession });
        for (const [turnId, sequence] of this.lastSequences) {
          this.command("stream.resume", { turn_id: turnId, after_sequence: sequence });
        }
        while (this.pending.length) this.sendNow(this.pending.shift()!);
      }
      if (event.turn_id && event.sequence != null) {
        this.lastSequences.set(event.turn_id, Math.max(event.sequence, this.lastSequences.get(event.turn_id) ?? 0));
      }
      this.onEvent(event);
      if (event.turn_id && ["chat.completed", "chat.error", "chat.cancelled"].includes(event.type)) {
        this.lastSequences.delete(event.turn_id);
      }
    };
    this.socket.onclose = () => {
      this.socket = null;
      this.ready = false;
      if (this.stopped) {
        this.onStatus("offline");
        return;
      }
      this.onStatus("reconnecting");
      const delay = Math.min(10_000, 500 * 2 ** this.reconnectAttempt++);
      this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
    };
  }

  setSession(sessionId: string | null): void {
    const open = this.isReady();
    if (open && this.activeSession && this.activeSession !== sessionId) {
      this.command("session.unsubscribe", { session_id: this.activeSession });
    }
    this.activeSession = sessionId;
    if (sessionId && open) this.command("session.subscribe", { session_id: sessionId });
    else if (sessionId) this.connect();
  }

  resume(turnId: string, afterSequence = 0): void {
    this.lastSequences.set(turnId, afterSequence);
    if (this.isReady()) {
      this.command("stream.resume", { turn_id: turnId, after_sequence: afterSequence });
    } else {
      this.connect();
    }
  }

  sendChat(sessionId: string, content: string, requestId: string): void {
    this.command("chat.send", { session_id: sessionId, content, idempotency_key: requestId }, requestId);
  }

  cancel(turnId: string): void {
    this.command("chat.cancel", { turn_id: turnId });
  }

  command(type: string, payload: Record<string, unknown>, requestId: string = crypto.randomUUID()): void {
    const command: Command = { v: "1", type, request_id: requestId, payload };
    if (this.isReady()) this.sendNow(command);
    else {
      this.pending.push(command);
      this.connect();
    }
  }

  close(): void {
    this.stopped = true;
    if (this.reconnectTimer != null) window.clearTimeout(this.reconnectTimer);
    this.socket?.close(1000, "student ui closed");
    this.socket = null;
    this.ready = false;
  }

  private sendNow(command: Command): void {
    this.socket?.send(JSON.stringify(command));
  }

  private isReady(): boolean {
    return this.ready && this.socket?.readyState === WebSocket.OPEN;
  }
}
