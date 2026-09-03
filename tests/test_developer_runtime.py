import pytest


@pytest.mark.asyncio
async def test_mcp_connection_test_reuses_stored_hidden_credentials(monkeypatch):
    from core import mcp_runtime
    from server.web import developer_runtime

    captured: dict[str, object] = {}

    class FakeCatalog:
        def names(self) -> list[str]:
            return []

    class FakeRuntime:
        def __init__(self, _catalog: FakeCatalog) -> None:
            pass

        async def connect_all(self, configs: dict[str, object]) -> None:
            captured.update(configs)

        async def close(self) -> None:
            pass

    monkeypatch.setattr(developer_runtime, "ToolCatalog", FakeCatalog)
    monkeypatch.setattr(mcp_runtime, "MCPRuntime", FakeRuntime)
    monkeypatch.setattr(
        developer_runtime,
        "load_runtime_overrides",
        lambda: {
            "tools": {
                "mcp_servers": {
                    "secured": {
                        "env": {"MCP_TOKEN": "secret"},
                        "headers": {"Authorization": "Bearer secret"},
                    }
                }
            }
        },
    )

    result = await developer_runtime.test_mcp_server(
        "secured",
        {"transport": "stdio", "command": "python", "args": []},
    )

    config = captured["secured"]
    assert config.env == {"MCP_TOKEN": "secret"}
    assert config.headers == {"Authorization": "Bearer secret"}
    assert result == {"ok": True, "server": "secured", "tools": []}
