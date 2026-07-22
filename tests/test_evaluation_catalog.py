from pathlib import Path

import yaml

from evaluation.core.catalog import discover_suites, latest_run_path, resolve_suite


def _dataset(suite_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "suite": {"id": suite_id, "name": f"{suite_id} suite"},
        "cases": [{"id": "case", "input": "question", "expectation": {}}],
    }


def test_catalog_discovers_suites_and_isolates_runs_and_markdown_results(tmp_path):
    suites_root = tmp_path / "suites"
    runs_root = tmp_path / "runs"
    results_root = tmp_path / "result"
    dataset_path = suites_root / "alpha-v1" / "dataset.yaml"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(yaml.safe_dump(_dataset("alpha-v1")), encoding="utf-8")

    suites = discover_suites(suites_root=suites_root, runs_root=runs_root, results_root=results_root)
    suite = resolve_suite("alpha-v1", suites=suites)

    assert list(suites) == ["alpha-v1"]
    assert suite.dataset_path == dataset_path
    assert suite.runs_dir == runs_root / "alpha-v1"
    assert suite.results_dir == results_root / "alpha-v1"


def test_catalog_discovers_a_suite_without_validating_its_runner_specific_case_schema(tmp_path):
    suites_root = tmp_path / "suites"
    dataset_path = suites_root / "guided-v1" / "dataset.yaml"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(
        yaml.safe_dump({
            "schema_version": "1.0",
            "suite": {"id": "guided-v1", "name": "guided suite"},
            "blueprint_path": "blueprint.yaml",
            "cases": [{"id": "case", "turn_budget": 6, "student_profile": {"role": "student"}}],
        }),
        encoding="utf-8",
    )

    suites = discover_suites(suites_root=suites_root)

    assert suites["guided-v1"].dataset_path == dataset_path


def test_catalog_uses_latest_report_within_the_selected_suite_only(tmp_path):
    runs_root = tmp_path / "runs"
    first = runs_root / "alpha-v1" / "20260720-100000.json"
    latest = runs_root / "alpha-v1" / "20260721-100000.json"
    foreign = runs_root / "beta-v1" / "20260722-100000.json"
    for path in (first, latest, foreign):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    assert latest_run_path(runs_root / "alpha-v1") == latest


def test_installed_suite_directory_names_match_their_declared_suite_ids():
    suites = discover_suites()

    assert {"nlp-tool-routing-v1", "nlp-tool-orchestration-v1"} <= set(suites)
    assert all(suite.dataset_path.parent.name == suite.id for suite in suites.values())


def test_evaluation_layout_separates_shared_engine_from_each_suite_home():
    root = Path(__file__).parents[1] / "evaluation"

    assert (root / "core" / "catalog.py").is_file()
    assert (root / "tool_routing" / "README.md").is_file()
    assert (root / "tool_orchestration" / "README.md").is_file()
    assert not (root / "catalog.py").exists()
