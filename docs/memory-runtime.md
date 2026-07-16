# Scoped Memory Runtime

NLP keeps all local memory under one root, `.data/memory`, while separating
ownership inside that root. It does not use embeddings, a vector database, or
RAG. Current web facts should be obtained with web search; memory is reserved
for user continuity and durable project decisions.

## Layout

```text
.data/memory/
├── users/<workspace+user>/
│   ├── MEMORY.md
│   └── topics/*.md
├── workspaces/<workspace>/
│   ├── MEMORY.md
│   └── topics/*.md
├── archives/<workspace+user>/history.jsonl
├── state/<workspace+user>/curator.json
└── .scoped-memory-migrated
```

Each scope keeps a generated `MEMORY.md` catalog, preserving the useful
"one master memory index" model. Scope directory names are URL-safe encodings,
so user-controlled identifiers never become raw paths.

Legacy `.data/memory/*.md` topics are copied into the default workspace on the
first scoped access. Originals are retained for rollback.

## Ownership

- User scope: profile, preferences, feedback, and corrections. Shared only by
  the same `workspace_id + user_id` across sessions.
- Workspace scope: project context, durable decisions, constraints, and ongoing
  goals. Shared by users explicitly operating in that workspace.
- Session archive: compressed history rows carry a `session_id`; runtime prompt
  injection only reads rows belonging to the current session.
- Worker: receives no automatic long-term-memory injection and cannot write it.
  The Coordinator supplies only task-relevant context.

## Turn flow

1. `SessionContext` resolves workspace, user, session, channel, and agent.
2. Coordinator loads a bounded snapshot of user and workspace memory.
3. The snapshot is inserted as a transient `SystemMessage`, never concatenated
   into the user's message and never persisted as new user evidence.
4. Context Collapse or Auto-Compact appends its summary to `history.jsonl` with
   an idempotent source ID.
5. Once enough new archives exist, a background Curator processes them.
6. The Curator atomically updates topic Markdown and regenerates the relevant
   `MEMORY.md` catalog.

There is no per-turn memory-search model and no per-turn extraction model.

## What the Curator may keep

The Curator requires archive evidence and confidence of at least `0.8`. It may
keep explicit stable user facts, preferences, corrections, durable project
decisions and constraints, or cross-session goals.

It ignores transient requests, logs, tool output, model inference, secrets,
credentials, and web facts that can be searched again. Automatic deletion is
disabled; a user or API caller must explicitly forget memory.

## Durability and safety

- Topic and index writes use a temporary file, `fsync`, and `os.replace`.
- Archive rows are append-only JSONL and use monotonic cursors.
- Archive `source_id` values make compression callbacks idempotent.
- Scope-level locks serialize topic/index updates.
- Secret-like content is rejected before writing.
- Curator failures do not block or alter the main conversation.

## WebUI/API boundary

`LocalMemoryService` exposes scoped `inspect`, `remember`, `forget`, and
`curate` operations. Every call requires a validated `SessionContext`; clients
must not construct filesystem paths directly.

Configuration lives under `memory` in `configs/agent_config.yaml`:

```yaml
memory:
  enabled: true
  max_injection_tokens: 6000
  max_topics: 12
  recent_archive_tokens: 2000
  curate_after_archives: 8
```
