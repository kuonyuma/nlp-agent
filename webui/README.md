# NLP Agent WebUI

Independent React/Vite frontend for the Pro_NLP FastAPI gateway.

## Development

```powershell
npm install
npm run dev
```

FastAPI should run at `http://127.0.0.1:8765`; Vite runs at
`http://127.0.0.1:5173` and proxies `/api`, `/health`, and `/ws`.

## Verification

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
```
