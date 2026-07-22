from pathlib import Path

import pytest

from core.prompt_runtime import PromptComposer, PromptRegistry, PromptRenderer, PromptValidationError


def test_registered_prompt_renders_and_tracks_version() -> None:
    registry = PromptRegistry()
    renderer = PromptRenderer(registry)

    assert registry.get("coordinator").version == "1.0"
    assert "Worker A" in renderer.render("coordinator", worker_profiles="Worker A")


def test_prompt_runtime_can_select_stronger_versioned_templates() -> None:
    registry = PromptRegistry(
        versions={"coordinator": "1.3", "worker": "1.2", "learning.policy": "1.2"}
    )
    renderer = PromptRenderer(registry)

    assert registry.get("coordinator").version == "1.3"
    assert "先明确目标、范围、约束和完成标准" in renderer.render(
        "coordinator", worker_profiles="Worker A"
    )
    assert "你是 Nova" in renderer.render(
        "coordinator", worker_profiles="Worker A"
    )
    assert "Nova 的 Worker" in renderer.render("worker", today="2026-07-18")
    assert registry.get("learning.policy").version == "1.2"
    assert "Nova" in renderer.render(
        "learning.policy", topic_policy="topic", progress_policy="progress"
    )


def test_missing_or_unexpected_variables_fail_before_model_call() -> None:
    renderer = PromptRenderer(PromptRegistry())

    with pytest.raises(PromptValidationError, match="Missing variable: worker_profiles"):
        renderer.render("coordinator")
    with pytest.raises(PromptValidationError, match="Unexpected variable: extra"):
        renderer.render("coordinator", worker_profiles="none", extra="nope")


def test_socratic_prompt_accepts_its_guided_blueprint_snapshot() -> None:
    renderer = PromptRenderer(PromptRegistry())

    rendered = renderer.render(
        "learning.mode.socratic", guided_session="{}", guided_blueprint="{}"
    )

    assert "assigned_guided_blueprint" in rendered


def test_template_declarations_are_validated(tmp_path: Path) -> None:
    (tmp_path / "coordinator.md").write_text("hello {{undeclared}}", encoding="utf-8")
    registry = PromptRegistry(templates_dir=tmp_path)

    with pytest.raises(PromptValidationError, match="used but undeclared"):
        PromptRenderer(registry).render("coordinator", worker_profiles="workers")


def test_composer_keeps_skill_sop_outside_the_prompt_registry() -> None:
    renderer = PromptRenderer(PromptRegistry())
    text = PromptComposer(renderer).compose(
        [("worker", {"today": "2026-07-18"}), "[Skill SOP]\nUse evidence only."]
    )

    assert "2026-07-18" in text
    assert "[Skill SOP]" in text
