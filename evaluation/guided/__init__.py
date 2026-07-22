"""Multi-turn, blueprint-bound guided-learning evaluation.

This package is deliberately separate from the production Agent runtime.  It
drives an already-running Gateway through an adapter and keeps all evaluator
state in memory plus `.jbeval/runs` artifacts.
"""

from evaluation.guided.architecture import GuidedArchitectureJudge
from evaluation.guided.dataset import load_guided_dataset
from evaluation.guided.http_executor import HttpGuidedGatewayExecutor
from evaluation.guided.runner import GuidedEvaluationRunner

__all__ = ["GuidedArchitectureJudge", "GuidedEvaluationRunner", "HttpGuidedGatewayExecutor", "load_guided_dataset"]
