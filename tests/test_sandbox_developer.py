from __future__ import annotations


def test_runtime_state_summary_has_dashboard_states() -> None:
    from server.sandbox.developer import summarize_runtime_states

    assert summarize_runtime_states([("ready_unbound", 2), ("failed", 1)]) == {
        "creating": 0, "ready_unbound": 2, "claiming": 0, "assigned": 0, "draining": 0, "failed": 1,
    }


def test_developer_catalog_exposes_sandbox_route() -> None:
    from server.rbac.catalog import MENU_CATALOG

    assert any(item[2] == "/developer/sandbox" for item in MENU_CATALOG)
