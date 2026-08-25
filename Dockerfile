# syntax=docker/dockerfile:1

# Build the two Vite applications once; FastAPI serves the resulting static files.
FROM node:22-bookworm-slim AS web-builder
WORKDIR /build/webui

COPY webui/package.json webui/package-lock.json ./
RUN npm ci

COPY webui/ ./
RUN npm run build && npm run build:monitor

# Keep the runtime image focused on the Python service and prebuilt assets.
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    UV_LINK_MODE=copy
WORKDIR /app

# The isolated Sandbox Manager invokes the host Docker Engine through the
# explicitly mounted socket in compose.  The Web service never mounts it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . ./
COPY --from=web-builder /build/webui/dist ./webui/dist
COPY --from=web-builder /build/webui/monitor-dist ./webui/monitor-dist

RUN mkdir -p /app/.data/gateway

EXPOSE 8765 8766
CMD [".venv/bin/python", "main.py", "serve"]
