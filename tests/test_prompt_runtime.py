from pathlib import Path

import pytest

from core.prompt_runtime import PromptComposer, PromptRegistry, PromptRenderer, PromptValidationError


def test_registered_prompt_renders_and_tracks_version() -> None:
    registry = PromptRegistry()
    renderer = PromptRenderer(registry)

    assert registry.get("coordinator").version == "1.0"
    assert "Worker A" in renderer.render("coordinator", worker_profiles="Worker A")


def test_prompt_runtime_can_select_stronger_versioned_templates() -> None:
    registry = PromptRegistry(versions={"coordinator": "1.1", "worker": "1.1"})
    renderer = PromptRenderer(registry)

    assert registry.get("coordinator").version == "1.1"
    assert "先明确目标、范围、约束和完成标准" in renderer.render(
        "coordinator", worker_profiles="Worker A"
    )
    assert "结果格式" in renderer.render("worker", today="2026-07-18")


def test_missing_or_unexpected_variables_fail_before_model_call() -> None:
    renderer = PromptRenderer(PromptRegistry())

    with pytest.raises(PromptValidationError, match="Missing variable: worker_profiles"):
        renderer.render("coordinator")
    with pytest.raises(PromptValidationError, match="Unexpected variable: extra"):
        renderer.render("coordinator", worker_profiles="none", extra="nope")


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
