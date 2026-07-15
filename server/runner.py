"""Runtime construction helpers for embedded hosts.

Hosts must submit both user turns and Worker completion events through
``CoordinatorRuntime``.  This module intentionally does not run a second
queue consumer or call ``app.ainvoke`` directly.
"""

from core.coordinator_runtime import CoordinatorRuntime, InvokeCoordinator
from core.worker_events import global_worker_event_bus


def create_coordinator_runtime(invoke: InvokeCoordinator) -> CoordinatorRuntime:
    return CoordinatorRuntime(global_worker_event_bus, invoke)
