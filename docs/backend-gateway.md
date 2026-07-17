# Backend Gateway Core

The Backend Gateway is the only owner of Coordinator, Worker, LangGraph,
tool, memory, telemetry, and local persistence lifecycles.

```text
Browser / CLI / future channels
             |
       FastAPI adapter
             |
      BackendGateway
       /     |      \
 Turn store Events  LangGraphAgentEngine
   SQLite   SQLite       |
                    Coordinator/Worker
```

## Hosting rules

- Construct one `BackendGateway` per OS process.
- Call `await gateway.start()` during host startup.
- Route every turn, injection, cancellation, approval, and session deletion
  through the Gateway.
- Call `await gateway.close()` during graceful shutdown.
- Do not run several Uvicorn workers with embedded Gateway instances. A future
  FastAPI layer may scale independently only when it talks to the single
  Gateway over an internal transport.

## Durable streaming

Every Gateway event has a per-turn monotonic `sequence`. Clients reconnect with
their last sequence and call `replay_events()` before resuming `stream_events()`.
The SQLite event log is authoritative; bounded live queues are only a latency
optimization.

## Security boundary

HTTP adapters must construct `AuthenticatedPrincipal` from authenticated server
credentials. User and workspace identifiers must never be trusted from request
JSON. Session, Turn, Memory, Worker control, and Trace access are checked against
that principal before data is returned or mutated.
