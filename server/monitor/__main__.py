"""Run the isolated observability monitor server."""

import uvicorn

from configs.settings import settings


def run() -> None:
    config = settings.monitor_runtime
    uvicorn.run(
        "server.monitor.app:app",
        host=str(config.get("host", "127.0.0.1")),
        port=int(config.get("port", 8766)),
        workers=1,
    )


if __name__ == "__main__":
    run()
