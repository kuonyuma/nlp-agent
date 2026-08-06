"""Compatibility facade over the typed provider/model runtime."""

from core.model_runtime.factory import get_global_model_factory
from core.model_runtime.runtime import ResilientChatModel
from core.model_runtime.selection import current_model_profile
from configs.settings import settings


def _selected_profile(requested: str | None = None) -> str | None:
    return requested or current_model_profile()


def get_planner_llm(model_profile: str | None = None) -> ResilientChatModel:
    factory = get_global_model_factory()
    if selected := _selected_profile(model_profile):
        return factory.build_preset(factory.profile_preset(selected, "coordinator"))
    return factory.build_route("coordinator")


def resolve_worker_model_name(
    agent_name: str | None = None,
    requested_model: str | None = None,
    model_profile: str | None = None,
) -> str:
    if settings.NLP_AGENT_WORKER_MODEL:
        return settings.NLP_AGENT_WORKER_MODEL
    factory = get_global_model_factory()
    if selected := _selected_profile(model_profile):
        return factory.profile_preset(selected, "worker")
    return settings._resolve_worker_model(agent_name, requested_model)


def get_tool_llm(model_profile: str | None = None) -> ResilientChatModel:
    """Return the selected profile's Worker model or the default Worker route."""
    return get_worker_llm(model_profile=model_profile)


def get_utility_llm(model_profile: str | None = None) -> ResilientChatModel:
    """Return the selected profile's utility model for compression and curation."""
    factory = get_global_model_factory()
    if selected := _selected_profile(model_profile):
        return factory.build_preset(factory.profile_preset(selected, "utility"))
    return factory.build_route("utility")


def get_worker_llm(
    agent_name: str | None = None,
    tool_specified_model: str | None = None,
    model_profile: str | None = None,
) -> ResilientChatModel:
    factory = get_global_model_factory()
    selected = _selected_profile(model_profile)
    requested = resolve_worker_model_name(
        agent_name, tool_specified_model, model_profile
    )
    if selected and requested == factory.profile_preset(selected, "worker"):
        return factory.build_preset(requested)
    default = settings._config.get("model_routes", {}).get("worker", {}).get("primary")
    if requested == default:
        return factory.build_route("worker")
    return factory.build_override(requested, base_route="worker")
