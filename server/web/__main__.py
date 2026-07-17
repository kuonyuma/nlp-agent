"""Run the single-process FastAPI + BackendGateway service."""

from __future__ import annotations

import uvicorn

from configs.settings import settings


def run() -> None:
    config = settings.web_runtime
    uvicorn.run(
        "server.web.app:app",
        host=str(config.get("host", "127.0.0.1")),
        port=int(config.get("port", 8765)),
        workers=1,
        ws_max_size=int(config.get("max_ws_message_bytes", 1_048_576)),
    )


if __name__ == "__main__":
    run()
