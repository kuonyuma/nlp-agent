"""Function Calling definitions for deterministic NLP teaching calculations."""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

from core.nlp.bleu import score_bleu, score_corpus_bleu
from core.nlp.classification_metrics import precision_recall_curve
from core.nlp.ngrams import analyze_ngrams
from core.nlp.retrieval_metrics import precision_at_n
from core.nlp.tfidf import analyze_tfidf
from core.tool_runtime import ToolDescriptor, ToolRisk, ToolScope, ToolSource


TOOL_MANIFEST = {
    "id": "nlp-teaching-tools",
    "version": "1.0",
    "category": "nlp",
    "prompt_priority": 200,
    "scopes": ["coordinator", "worker"],
    "capabilities": ["nlp.analyze"],
    "risk": "low",
}


class TfidfInput(BaseModel):
    documents: list[str] = Field(min_length=1, max_length=100)
    query: str
    tokenization: Literal["character", "whitespace"] = "character"


class PrecisionRecallInput(BaseModel):
    labels: list[int] = Field(min_length=1, max_length=10_000)
    scores: list[float] = Field(min_length=1, max_length=10_000)


class RankedResult(BaseModel):
    id: str
    relevant: bool


class PrecisionAtNInput(BaseModel):
    ranked_results: list[RankedResult] = Field(max_length=10_000)
    ks: list[int] = Field(min_length=1, max_length=20)


class NgramInput(BaseModel):
    candidate: str
    references: list[str] = Field(min_length=1, max_length=10)
    n_values: list[int] = Field(min_length=1, max_length=4)
    tokenization: Literal["character", "whitespace"] = "character"


class BleuInput(BaseModel):
    mode: Literal["sentence", "corpus"] = "sentence"
    candidate: str | None = None
    references: list[str] | None = Field(default=None, max_length=10)
    candidates: list[str] | None = Field(default=None, min_length=1, max_length=100)
    references_per_candidate: list[list[str]] | None = Field(default=None, min_length=1, max_length=100)
    max_n: int = Field(default=4, ge=1, le=4)
    tokenization: Literal["character", "whitespace"] = "character"

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "BleuInput":
        if self.mode == "sentence" and self.candidate is not None and self.references:
            return self
        if self.mode == "corpus" and self.candidates and self.references_per_candidate:
            return self
        raise ValueError("sentence mode needs candidate and references; corpus mode needs candidates and references_per_candidate")


async def tfidf_analyzer(**kwargs):
    return analyze_tfidf(**kwargs)


async def precision_recall_analyzer(**kwargs):
    return precision_recall_curve(**kwargs)


async def precision_at_n_analyzer(**kwargs):
    return precision_at_n(
        ranked_results=[item.model_dump() for item in kwargs["ranked_results"]],
        ks=kwargs["ks"],
    )


async def ngram_analyzer(**kwargs):
    return analyze_ngrams(**kwargs)


async def bleu_score(**kwargs):
    if kwargs["mode"] == "corpus":
        return score_corpus_bleu(
            candidates=kwargs["candidates"],
            references_per_candidate=kwargs["references_per_candidate"],
            max_n=kwargs["max_n"],
            tokenization=kwargs["tokenization"],
        )
    return score_bleu(
        candidate=kwargs["candidate"],
        references=kwargs["references"],
        max_n=kwargs["max_n"],
        tokenization=kwargs["tokenization"],
    )


def _tool(*, name: str, description: str, coroutine, schema: type[BaseModel]) -> ToolDescriptor:
    def factory() -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=coroutine, name=name, description=description, args_schema=schema
        )

    return ToolDescriptor(
        name=name,
        description=description,
        source=ToolSource.CUSTOM,
        scopes=frozenset({ToolScope.COORDINATOR, ToolScope.WORKER}),
        risk=ToolRisk.LOW,
        read_only=True,
        idempotent=True,
        concurrency_safe=True,
        factory=factory,
    )


TOOLS = [
    _tool(name="nlp_tfidf_analyzer", description="计算课件公式的 TF、DF、IDF、TF-IDF 与查询相关度。", coroutine=tfidf_analyzer, schema=TfidfInput),
    _tool(name="nlp_precision_recall_curve", description="按阈值计算 Precision、Recall、F1 与 PR 曲线数据。", coroutine=precision_recall_analyzer, schema=PrecisionRecallInput),
    _tool(name="nlp_precision_at_n", description="计算排序检索结果的 Precision@N。", coroutine=precision_at_n_analyzer, schema=PrecisionAtNInput),
    _tool(name="nlp_ngram_analyzer", description="仅在用户要求 n-gram 列表、匹配细节或 clipped count 时使用；生成 1 至 4-gram 并展示候选与参考文本的匹配。", coroutine=ngram_analyzer, schema=NgramInput),
    _tool(name="nlp_bleu_score", description="计算完整 BLEU：已包含 modified n-gram precision、几何平均和 Brevity Penalty。仅要求 BLEU 时只调用本工具，不要额外调用 nlp_ngram_analyzer。", coroutine=bleu_score, schema=BleuInput),
]
