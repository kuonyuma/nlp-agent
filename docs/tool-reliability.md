# Tool Reliability and Safety

The tool executor owns retries, locking, risk enforcement, result normalization,
and audit events. Model binding and execution still use the same immutable
`ToolSet`.

## Retry contract

Retries are opt-in through `ToolRetryPolicy` and are rejected at descriptor
validation time unless the tool is read-only or explicitly idempotent. Only
timeouts, network failures, and rate limits are retryable. Backoff is
exponential with bounded jitter. Validation, permission, ordinary execution,
and tool-reported business errors are never replayed automatically.

MCP transport failures reconnect the server but do not implicitly replay the
call. Configure MCP `read_only_tools` or `idempotent_tools` to let the central
executor safely retry a newly connected session.

## Concurrency

- `max_concurrency` provides a process-wide semaphore per tool.
- `lock_scope: session` serializes the tool only inside one session.
- `lock_scope: global` serializes it across all sessions and Workers.
- Legacy `exclusive: true` maps to a global lock.

Locks cover every retry attempt so an exclusive operation cannot interleave
with another call during backoff.

## High-risk grants

High-risk tools are denied while resolving a ToolSet and checked again at
execution. A short-lived grant requires `session_id`, `granted_by`, reason, and
TTL. Releasing a Coordinator session revokes all of its grants. WebUI/API code
uses `PhysicalToolManager.grant_high_risk_tool()` and rebuilds the ToolSet with
`allow_high_risk=True`.

## Audit

Every denial, attempt, retry, and completion is appended to
`.data/tool-audit/<encoded-session>.jsonl` and exposed through
`recent_tool_audit()`. Audit rows include tool/provider, role/profile, attempt,
outcome, error kind, duration, and argument names. Argument values and tool
outputs are intentionally excluded.
