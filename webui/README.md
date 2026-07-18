# NLP Agent WebUI

Independent React/Vite frontend for the Pro_NLP FastAPI gateway.

## Student experience

- Nanobot-inspired responsive session sidebar and streaming thread shell.
- Same-origin cookie authentication and CSRF-protected HTTP mutations.
- Multiplexed `/ws/v1` commands, reconnect, sequence resume, and gap recovery.
- Educational activity labels for reasoning, tools, and worker collaboration.
- Markdown, GFM, math, lazy syntax highlighting, learning context, concepts,
  practice prompts, progress, summaries, favorites, archives, and report export.

Backend Sessions, Turns, transcripts, and runtime events remain authoritative.
UI-only learning metadata (titles, topics, favorites, archives, summaries, and
concept chips) is isolated in `localStorage` under
`nlp-agent.learning-preferences.v1` until dedicated teacher/course APIs exist.

## Development

```powershell
npm install
npm run dev
```

FastAPI should run at `http://127.0.0.1:8765`; Vite runs at
`http://127.0.0.1:5173` and proxies `/api`, `/health`, and `/ws`.

For a production-style local run, build first and start FastAPI. The backend
serves `webui/dist` at `/` according to `configs/agent_config.yaml`.

## Verification

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
```
