"""Deterministic, dependency-free question analysis used before a data platform exists."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any


CONTEXT = re.compile(r"^<!-- nlp-learning-context:(.*?) -->\s*", re.S)
PUNCTUATION = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)

TOPIC_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Transformer 与注意力", ("transformer", "attention", "注意力", "self-attention", "自注意力", "位置编码")),
    ("大语言模型", ("llm", "大模型", "语言模型", "prompt", "提示词", "token", "微调", "rlhf")),
    ("词向量与表示", ("embedding", "词向量", "word2vec", "bert", "表示学习", "向量")),
    ("文本分类", ("文本分类", "classification", "分类器", "朴素贝叶斯", "svm")),
    ("情感分析", ("情感", "sentiment", "观点", "极性")),
    ("信息抽取", ("实体识别", "ner", "关系抽取", "信息抽取", "实体", "槽位")),
    ("机器翻译", ("机器翻译", "translation", "翻译", "bleu", "seq2seq")),
    ("句法分析", ("句法", "syntax", "依存", "成分分析", "语法树")),
    ("语义与语用", ("语义", "semantic", "语用", "pragmatic", "指代", "歧义")),
    ("分词与形态学", ("分词", "tokenization", "形态", "morphology", "词性", "pos")),
    ("评估与实验", ("准确率", "召回率", "f1", "评估", "指标", "实验", "过拟合")),
    ("工程实现", ("代码", "python", "pytorch", "报错", "debug", "部署", "api")),
]

TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("调试排错", ("报错", "错误", "为什么不", "失败", "debug", "exception")),
    ("代码实现", ("代码", "实现", "python", "pytorch", "怎么写", "示例")),
    ("概念辨析", ("区别", "对比", "异同", "vs", "关系")),
    ("原理解释", ("是什么", "为什么", "原理", "解释", "如何理解")),
    ("应用分析", ("应用", "场景", "怎么用", "案例", "适合")),
    ("练习求解", ("计算", "证明", "这道题", "答案", "求解", "练习")),
]

ADVANCED = ("推导", "证明", "复杂度", "梯度", "损失函数", "架构", "优化", "微调", "对齐", "机制", "源码")
BEGINNER = ("是什么", "入门", "概念", "简单", "举例", "区别")


def clean_question(raw: str) -> tuple[str, dict[str, Any]]:
    match = CONTEXT.match(raw)
    context: dict[str, Any] = {}
    if match:
        try:
            context = json.loads(match.group(1))
        except (TypeError, ValueError):
            context = {}
        raw = raw[match.end():]
    raw = re.sub(r"^\[学习设置.*?]\s*", "", raw, flags=re.S)
    return raw.strip(), context


def _match(text: str, rules: list[tuple[str, tuple[str, ...]]], fallback: str) -> str:
    lowered = text.lower()
    scores = [(sum(lowered.count(word) for word in words), label) for label, words in rules]
    score, label = max(scores, default=(0, fallback))
    return label if score else fallback


def _difficulty(text: str, context: dict[str, Any]) -> str:
    declared = context.get("level")
    if declared in {"beginner", "intermediate", "advanced"}:
        return str(declared)
    lowered = text.lower()
    score = sum(word in lowered for word in ADVANCED) * 2 + (len(text) > 120) + (text.count("?") + text.count("？") > 1)
    score -= sum(word in lowered for word in BEGINNER)
    return "advanced" if score >= 3 else "beginner" if score <= 0 else "intermediate"


def _keywords(text: str, topic: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", text.lower())
    stop = {"什么", "为什么", "怎么", "如何", "可以", "这个", "一下", "请问", "区别", "解释"}
    ranked = Counter(word for word in words if word not in stop)
    result = [word for word, _ in ranked.most_common(5)]
    if not result and topic != "NLP 综合":
        result.append(topic)
    return result


def classify(row: dict[str, Any]) -> dict[str, Any]:
    question, context = clean_question(str(row.get("input_text", "")))
    topic = _match(question, TOPIC_RULES, str(context.get("topic") or "NLP 综合"))
    question_type = _match(question, TYPE_RULES, "开放问答")
    return {
        "turn_id": row["turn_id"], "session_id": row["session_id"],
        "user_id": row["user_id"], "workspace_id": row["workspace_id"],
        "question": question, "topic": topic, "question_type": question_type,
        "difficulty": _difficulty(question, context), "keywords": _keywords(question, topic),
        "status": row["status"], "created_at": row["created_at"],
        "has_error": bool(row.get("error_kind")),
    }


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    questions = [classify(row) for row in rows if str(row.get("input_text", "")).strip()]
    topic_counts = Counter(item["topic"] for item in questions)
    difficulty_counts = Counter(item["difficulty"] for item in questions)
    type_counts = Counter(item["question_type"] for item in questions)
    fingerprints: dict[str, list[dict[str, Any]]] = defaultdict(list)
    topic_sessions: dict[str, set[str]] = defaultdict(set)
    topic_errors: Counter[str] = Counter()
    for item in questions:
        fingerprint = PUNCTUATION.sub("", item["question"].lower())[:100]
        fingerprints[fingerprint].append(item)
        topic_sessions[item["topic"]].add(item["session_id"])
        if item["has_error"]:
            topic_errors[item["topic"]] += 1
    frequent = sorted(
        ({"question": items[0]["question"], "count": len(items), "topic": items[0]["topic"], "question_type": items[0]["question_type"]} for items in fingerprints.values()),
        key=lambda item: (-item["count"], item["question"]),
    )[:20]
    weak = []
    for topic, count in topic_counts.items():
        repeated = sum(max(0, len(items) - 1) for items in fingerprints.values() if items[0]["topic"] == topic)
        advanced = sum(item["difficulty"] == "advanced" for item in questions if item["topic"] == topic)
        errors = topic_errors[topic]
        score = count + repeated * 2 + advanced + errors * 3
        weak.append({"topic": topic, "score": score, "questions": count, "repeat_questions": repeated, "errors": errors, "sessions": len(topic_sessions[topic]), "risk": "high" if score >= 10 else "medium" if score >= 5 else "low"})
    weak.sort(key=lambda item: (-item["score"], item["topic"]))
    total = len(questions)
    distribution = lambda counter: [{"name": name, "count": count, "percentage": round(count / total * 100, 2) if total else 0.0} for name, count in counter.most_common()]
    return {
        "summary": {"questions": total, "sessions": len({item["session_id"] for item in questions}), "students": len({item["user_id"] for item in questions}), "error_questions": sum(item["has_error"] for item in questions)},
        "questions": questions, "frequent_questions": frequent,
        "weak_topics": weak, "topic_distribution": distribution(topic_counts),
        "difficulty_distribution": distribution(difficulty_counts),
        "type_distribution": distribution(type_counts),
    }
