from configs.settings import Settings


def test_fixed_auth_defaults_to_universal_roles(monkeypatch) -> None:
    monkeypatch.delenv("NLP_AGENT_AUTH_ROLES", raising=False)

    configured = Settings(_env_file=None)

    assert configured.NLP_AGENT_AUTH_ROLES == "student,teacher,admin"
