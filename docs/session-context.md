# Session and Context Runtime

Every request must carry `configurable.thread_id`. `SessionContext` expands that
identity with `user_id`, `workspace_id`, `channel`, and `agent_id`; its encoded
storage key prevents filename collisions and path traversal. Coordinator and
each Worker therefore receive separate context state even inside one session.

The local runtime keeps three explicit layers:

- LangGraph checkpoint: executable Coordinator state.
- append-only JSONL transcript: audit and WebUI display history.
- `context-state.json`: per-agent collapse commits and compaction metadata.

`LocalSessionService` provides WebUI-friendly create/list/messages/delete
operations without reading or changing a process-global active session.
`CoordinatorRuntime.release_session()` cancels and releases only the selected
session.

## Five-layer model view

`ContextManager.prepare()` builds a temporary model-facing view under one
per-session lock:

1. Large tool results are externalized by the tool persistence layer.
2. Re-fetchable old tool results are micro-compacted.
3. Coordinator-directed Snip uses the current call's `thread_id`.
4. Context Collapse projects persisted per-session summaries.
5. Auto-Compact summarizes near the limit; legal hard trimming is the final
   overflow guard.

The append-only transcript is not destructively rewritten by read-time
projection.

## Token budget

Provider configuration declares `context_window_tokens` and
`output_reserve_tokens`. The actual model input limit subtracts output reserve,
safety margin, and bound tool-schema tokens. Estimates include message framing,
tool calls, tool results, artifacts, JSON punctuation, and conservative mixed
CJK/Latin costs. Historical API `total_tokens` is never reused as if it were the
size of a transformed context view.
