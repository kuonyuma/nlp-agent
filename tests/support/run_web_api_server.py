from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from gateway.core import BackendGateway  # noqa: E402
from gateway.repository import GatewayRepository  # noqa: E402
from server.web.app import create_app  # noqa: E402
from server.web.auth import SameOriginSessionAuth  # noqa: E402
from test_web_api import FakeEngine, FakeSessions  # noqa: E402


def main() -> None:
    port = int(sys.argv[1])
    origin = f"http://127.0.0.1:{port}"
    temporary = tempfile.TemporaryDirectory(prefix="pro-nlp-web-api-")
    database = Path(temporary.name) / "gateway.sqlite3"
    engine = FakeEngine()
    sessions = FakeSessions()

    def gateway_factory() -> BackendGateway:
        return BackendGateway(
            engine=engine,
            repository=GatewayRepository(database),
            sessions=sessions,
        )

    auth = SameOriginSessionAuth(
        secret="integration-test-secret-that-is-long-enough",
        allowed_origins=[origin],
    )
    app = create_app(gateway_factory=gateway_factory, auth=auth)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
