# FastAPI Web Adapter

FastAPI is the same-origin network boundary for the WebUI. It owns HTTP,
WebSocket, signed-cookie authentication, CSRF validation, request validation,
and public event names. It never constructs LangGraph, Coordinator, or Worker
objects; the application lifespan starts and closes exactly one
`BackendGateway`.

```mermaid
flowchart LR
    UI["React WebUI"] -->|"HTTP control plane"| API["FastAPI :8765"]
    UI <-->|"WebSocket realtime plane /ws/v1"| API
    API -->|"direct async Python calls"| GW["BackendGateway"]
    GW --> STORE["SQLite Turn / Event / Outbox"]
    GW --> ENGINE["LangGraphAgentEngine"]
    ENGINE --> AGENTS["Coordinator / Workers / Tools"]
```

## Start and lifecycle

```powershell
uv sync
uv run python main.py serve
```

The server binds to `127.0.0.1:8765` by default. Uvicorn must stay at one
worker while the Gateway is embedded. The FastAPI lifespan performs
`gateway.start()` before readiness succeeds and `gateway.close()` during
graceful shutdown.

Health probes:

- `GET /health/live`: the ASGI process is alive.
- `GET /health/ready`: the Gateway is initialized and accepting turns.

## Same-origin authentication

1. The WebUI sends `POST /api/v1/auth/session` from the same origin.
2. The server returns an HttpOnly, SameSite=Strict, HMAC-signed cookie and a
   CSRF token in the JSON response.
3. Every mutating HTTP request sends `X-CSRF-Token` and an `Origin` header.
4. The WebSocket handshake sends the cookie automatically and is accepted only
   when its `Origin` is same-origin or explicitly configured.

No long-lived credential is placed in a WebSocket query string. Configure
`NLP_AGENT_WEB_SECRET` so cookies remain valid across restarts. Set
`cookie_secure: true` when serving through HTTPS. The built-in issuer is a
single-user local mode; a later account system can replace the auth resolver
without changing Gateway APIs.

## HTTP control plane

All business APIs are under `/api/v1`:

- `/auth/session`: establish, inspect, or clear the browser session.
- `/sessions`: create/list sessions; session detail, transcript, turns, delete.
- `/chat/turns`: submit and inspect turns; replay events and cancel.
- `/chat/injections`: insert a new user message into an executing turn.
- `/tool-approvals`: grant a bounded high-risk tool capability.
- `/settings`: read effective runtime information and persist per-user WebUI
  preferences.
- `/protocol`: discover WebSocket commands, events, and limits.

OpenAPI is available at `/api/openapi.json` and interactive documentation at
`/api/docs`.

## WebSocket realtime plane

One `/ws/v1` connection multiplexes any number of sessions, following the same
useful idea as nanobot's WebUI channel. Unlike nanobot's current wire format,
the NLP protocol uses versioned command envelopes and durable event sequence
numbers.

Client command:

```json
{
  "v": "1",
  "type": "chat.send",
  "request_id": "browser-generated-id",
  "payload": {
    "session_id": "session-id",
    "content": "Explain NLP",
    "idempotency_key": "optional-retry-key"
  }
}
```

Server event:

```json
{
  "v": "1",
  "type": "chat.delta",
  "event_id": "durable-event-id",
  "session_id": "session-id",
  "turn_id": "turn-id",
  "sequence": 3,
  "timestamp": "2026-07-17T00:00:00Z",
  "payload": {"delta": "text"}
}
```

Commands are `chat.send`, `chat.inject`, `chat.cancel`, `session.subscribe`,
`session.unsubscribe`, `stream.resume`, and `ping`. `session.switch` is
intentionally absent: selecting a session is frontend state, while
`session.subscribe` controls server event delivery.

For reconnect recovery, the browser sends:

```json
{
  "v": "1",
  "type": "stream.resume",
  "request_id": "resume-id",
  "payload": {"turn_id": "turn-id", "after_sequence": 17}
}
```

The adapter subscribes to live events first, then replays SQLite events. It
deduplicates by `(turn_id, sequence)` and fills detected gaps before delivering
new live events, so a reconnect cannot silently reorder the stream.

## Adapting nanobot WebUI

The React layout and rendering components can be reused. Replace its bootstrap
token flow with `/api/v1/auth/session`, replace `new_chat`/`attach`/`message`
frames with the versioned commands above, and map nanobot `delta`,
`reasoning_delta`, `turn_end`, and `session_updated` handlers to `chat.delta`,
`chat.reasoning.delta`, `chat.completed`, and `session.updated`. HTTP history
loads from `/api/v1/sessions/{session_id}/messages`.
