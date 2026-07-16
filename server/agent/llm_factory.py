"""Compatibility facade over the typed provider/model runtime."""

from core.model_runtime.factory import get_global_model_factory
from core.model_runtime.runtime import ResilientChatModel
from configs.settings import settings


def get_planner_llm() -> ResilientChatModel:
    return get_global_model_factory().build_route("coordinator")


def get_tool_llm() -> ResilientChatModel:
    """Return the default Worker route, including configured fallbacks."""
    return get_global_model_factory().build_route("worker")


def get_utility_llm() -> ResilientChatModel:
    """Cheap non-thinking route for summaries, compression, and curation."""
    return get_global_model_factory().build_route("utility")


def get_worker_llm(
    agent_name: str | None = None,
    tool_specified_model: str | None = None,
) -> ResilientChatModel:
    requested = settings._resolve_worker_model(agent_name, tool_specified_model)
    default = settings._config.get("model_routes", {}).get("worker", {}).get("primary")
    if requested == default:
        return get_global_model_factory().build_route("worker")
    return get_global_model_factory().build_override(requested, base_route="worker")
