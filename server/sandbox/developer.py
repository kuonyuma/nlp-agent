from __future__ import annotations

RUNTIME_STATES = ("creating", "ready_unbound", "claiming", "assigned", "draining", "failed")


def summarize_runtime_states(rows: list[tuple[str, int]]) -> dict[str, int]:
    counts = {state: 0 for state in RUNTIME_STATES}
    for state, count in rows:
        if state in counts:
            counts[state] = count
    return counts
