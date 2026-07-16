"""Compatibility adapters for transcript and model-facing context trimming."""

from __future__ import annotations

from typing import List

from langchain_core.messages import BaseMessage

from configs.settings import settings
from server.agent.compression.context_manager import trim_legal_history
from server.agent.session_storage import TranscriptMessage
from utils.tokens import token_count_with_estimation


MAX_CONTEXT_TOKENS = 200_000  # Compatibility; runtime code uses _input_limit().


def _input_limit() -> int:
    context_window, output_reserve = settings.get_context_limits()
    return max(1, context_window - output_reserve - 2_000)


def compress_messages(
    messages: List[TranscriptMessage],
    max_tokens: int | None = None,
) -> List[TranscriptMessage]:
    """Keep recent complete user turns for transcript replay under the model budget."""
    limit = max_tokens or _input_limit()
    if token_count_with_estimation(messages) <= limit:
        return messages
    system = [item for item in messages if item.role == "system" or item.type == "system"]
    conversation = [item for item in messages if item not in system]
    turns: list[list[TranscriptMessage]] = []
    current: list[TranscriptMessage] = []
    for message in conversation:
        if message.role == "user" and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    used = token_count_with_estimation(system)
    kept: list[list[TranscriptMessage]] = []
    for turn in reversed(turns):
        cost = token_count_with_estimation(turn)
        if kept and used + cost > limit:
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    return system + [message for turn in kept for message in turn]


def trim_context(
    messages: List[BaseMessage],
    max_tokens: int | None = None,
) -> List[BaseMessage]:
    return trim_legal_history(messages, max_tokens or _input_limit())
