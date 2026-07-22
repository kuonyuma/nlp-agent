from __future__ import annotations

from evaluation.guided.architecture import GuidedArchitectureJudge
from evaluation.guided.dataset import load_guided_dataset
from evaluation.guided.http_executor import HttpGuidedGatewayExecutor
from evaluation.guided.models import GuidedRunSnapshot, GuidedTurnSnapshot


def test_guided_dataset_loads_the_isolated_blueprint_and_multiturn_case():
    dataset, _digest = load_guided_dataset(
        ".jbeval/suites/guided-multiturn-v1/dataset.yaml"
    )

    assert dataset.suite.id == "guided-multiturn-v1"
    assert dataset.blueprint.id == "guided-tfidf-retrieval-v1"
    assert dataset.cases[0].turn_budget == 6
    assert dataset.cases[0].learning_context.mode == "socratic"


def test_architecture_judge_reports_session_and_blueprint_breakage():
    report = GuidedArchitectureJudge().judge(
        GuidedRunSnapshot(
            case_id="reuse",
            chat_session_id="chat-1",
            guided_session_id="guided-1",
            blueprint_id="blueprint-1",
            turns=(
                GuidedTurnSnapshot(
                    turn_number=1,
                    turn_id="turn-1",
                    chat_session_id="chat-1",
                    guided_session_id="guided-1",
                    blueprint_id="blueprint-1",
                    turn_status="completed",
                    progress_attempts=1,
                ),
                GuidedTurnSnapshot(
                    turn_number=2,
                    turn_id="turn-2",
                    chat_session_id="chat-1",
                    guided_session_id="guided-2",
                    blueprint_id="blueprint-2",
                    turn_status="completed",
                    progress_attempts=1,
                ),
            ),
        )
    )

    assert report.verdict == "FAIL"
    assert "guided_session_changed" in report.failures
    assert "blueprint_changed" in report.failures
    assert "progress_attempt_not_increasing" in report.failures


def test_architecture_judge_accepts_a_continuous_multiturn_session():
    report = GuidedArchitectureJudge().judge(
        GuidedRunSnapshot(
            case_id="continuous",
            chat_session_id="chat-1",
            guided_session_id="guided-1",
            blueprint_id="blueprint-1",
            turns=tuple(
                GuidedTurnSnapshot(
                    turn_number=index,
                    turn_id=f"turn-{index}",
                    chat_session_id="chat-1",
                    guided_session_id="guided-1",
                    blueprint_id="blueprint-1",
                    turn_status="completed",
                    progress_attempts=index,
                )
                for index in range(1, 4)
            ),
        )
    )

    assert report.verdict == "PASS"
    assert report.metrics["completed_turn_rate"] == 1


def test_live_guided_executor_refuses_non_isolated_workspaces():
    try:
        HttpGuidedGatewayExecutor("http://127.0.0.1:8765", workspace_id="default")
    except ValueError as error:
        assert "evaluation-* workspace" in str(error)
    else:
        raise AssertionError("default workspace must not be accepted for live evaluation")
