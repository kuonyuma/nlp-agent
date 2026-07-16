from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Coordinator/Worker 模型配置。"""

    BASE_DIR: Path = BASE_DIR
    DEEPSEEK_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    NLP_AGENT_WORKER_MODEL: str = ""

    _config: dict = {}

    def __init__(self, **values):
        super().__init__(**values)
        yaml_path = BASE_DIR / "configs" / "agent_config.yaml"
        with yaml_path.open("r", encoding="utf-8") as file:
            self._config = yaml.safe_load(file) or {}

    def _get_llm_config(self, provider_name: str) -> dict:
        providers = self._config.get("providers", {})
        if provider_name not in providers:
            raise KeyError(
                f"模型提供方 '{provider_name}' 未配置，可用项：{list(providers)}"
            )
        config = providers[provider_name].copy()
        env_name = config.get("api_key_env", "DEEPSEEK_API_KEY")
        config["api_key"] = getattr(self, env_name, "")
        return config

    def get_context_limits(self, provider_name: str | None = None) -> tuple[int, int]:
        name = provider_name or self._config.get("defaults", {}).get(
            "coordinator", "deepseek-chat"
        )
        provider = self._config.get("providers", {}).get(name, {})
        return (
            int(provider.get("context_window_tokens", 200_000)),
            int(provider.get("output_reserve_tokens", 20_000)),
        )

    def _resolve_worker_model(
        self,
        agent_name: str | None = None,
        requested_model: str | None = None,
    ) -> str:
        if self.NLP_AGENT_WORKER_MODEL:
            return self.NLP_AGENT_WORKER_MODEL
        if requested_model:
            return requested_model
        agent_config = self._config.get("agents", {}).get(agent_name or "", {})
        if agent_config.get("model") not in (None, "inherit"):
            return agent_config["model"]
        default = self._config.get("defaults", {}).get("worker", "inherit")
        if default != "inherit":
            return default
        return self._config.get("defaults", {}).get("coordinator", "deepseek-chat")

    @property
    def planner_llm(self) -> dict:
        name = self._config.get("defaults", {}).get("coordinator", "deepseek-chat")
        return self._get_llm_config(name)

    @property
    def tool_llm(self) -> dict:
        return self._get_llm_config(self._resolve_worker_model())

    def resolve_worker_llm(
        self,
        agent_name: str | None = None,
        tool_specified_model: str | None = None,
    ) -> dict:
        name = self._resolve_worker_model(agent_name, tool_specified_model)
        return self._get_llm_config(name)

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        extra="ignore",
    )


settings = Settings()
