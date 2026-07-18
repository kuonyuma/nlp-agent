"""Application settings and compatibility accessors for typed model routes."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from core.runtime_config import load_runtime_config


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    BASE_DIR: Path = BASE_DIR
    DEEPSEEK_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    NLP_AGENT_WORKER_MODEL: str = ""
    NLP_AGENT_WEB_SECRET: str = ""

    _config: dict = {}

    def __init__(self, **values):
        super().__init__(**values)
        self._config = load_runtime_config()

    def _get_llm_config(self, name: str) -> dict:
        presets = self._config.get("model_presets", {})
        models = self._config.get("models", {})
        if name in presets:
            preset_name, preset, model_name = name, presets[name], presets[name]["model"]
        elif name in models:
            preset_name, preset, model_name = name, {"generation": {}, "thinking": {}}, name
        else:
            raise KeyError(f"Unknown model preset/model {name!r}; presets={list(presets)}")
        model = models[model_name]
        provider_name = model["provider"]
        provider = self._config.get("providers", {})[provider_name]
        env_name = provider.get("api_key_env", "DEEPSEEK_API_KEY")
        generation = preset.get("generation", {})
        thinking = preset.get("thinking", {})
        return {
            "preset": preset_name,
            "model_name": model_name,
            "model_id": model["model_id"],
            "provider": provider_name,
            "base_url": provider["base_url"],
            "api_key_configured": bool(getattr(self, env_name, "")),
            "context_window_tokens": int(model["context_window_tokens"]),
            "output_reserve_tokens": int(generation.get("max_output_tokens", 16_000)),
            "thinking_enabled": bool(thinking.get("enabled", False)),
            "reasoning_effort": thinking.get("effort", "none"),
        }

    def get_context_limits(self, preset_name: str | None = None) -> tuple[int, int]:
        name = preset_name or self._config.get("defaults", {}).get(
            "coordinator", "coordinator-pro"
        )
        preset_names = [name]
        for route in self._config.get("model_routes", {}).values():
            if route.get("primary") == name:
                preset_names.extend(route.get("fallbacks", []))
                break
        details = [self._get_llm_config(item) for item in preset_names]
        return (
            min(item["context_window_tokens"] for item in details),
            max(item["output_reserve_tokens"] for item in details),
        )

    @property
    def memory_runtime(self) -> dict:
        return dict(self._config.get("memory", {}))

    @property
    def prompt_runtime(self) -> dict:
        return dict(self._config.get("prompts", {}))

    def get_agent_runtime(self, role: str) -> dict:
        return dict(self._config.get("agent_runtime", {}).get(role, {}))

    @property
    def gateway_runtime(self) -> dict:
        return dict(self._config.get("gateway", {}))

    @property
    def web_runtime(self) -> dict:
        config = dict(self._config.get("web", {}))
        if self.NLP_AGENT_WEB_SECRET:
            config["auth_secret"] = self.NLP_AGENT_WEB_SECRET
        return config

    @property
    def monitor_runtime(self) -> dict:
        config = dict(self._config.get("monitor", {}))
        if self.NLP_AGENT_WEB_SECRET:
            config["auth_secret"] = self.NLP_AGENT_WEB_SECRET
        return config

    def _resolve_worker_model(
        self,
        agent_name: str | None = None,
        requested_model: str | None = None,
    ) -> str:
        if self.NLP_AGENT_WORKER_MODEL:
            return self.NLP_AGENT_WORKER_MODEL
        if requested_model not in (None, "", "inherit"):
            return str(requested_model)
        agent_config = self._config.get("agents", {}).get(agent_name or "", {})
        if agent_config.get("model") not in (None, "", "inherit"):
            return str(agent_config["model"])
        default = self._config.get("defaults", {}).get("worker", "inherit")
        if default != "inherit":
            return str(default)
        return str(self._config.get("defaults", {}).get("coordinator", "coordinator-pro"))

    def _resolve_model_name(
        self,
        agent_name: str | None = None,
        requested_model: str | None = None,
    ) -> str:
        """Compatibility alias retained for Worker metadata and recovery."""
        return self._resolve_worker_model(agent_name, requested_model)

    @property
    def planner_llm(self) -> dict:
        name = self._config.get("model_routes", {}).get("coordinator", {}).get(
            "primary", "coordinator-pro"
        )
        return self._get_llm_config(name)

    @property
    def tool_llm(self) -> dict:
        return self._get_llm_config(self._resolve_worker_model())

    def resolve_worker_llm(
        self,
        agent_name: str | None = None,
        tool_specified_model: str | None = None,
    ) -> dict:
        return self._get_llm_config(
            self._resolve_worker_model(agent_name, tool_specified_model)
        )

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        extra="ignore",
    )


settings = Settings()
