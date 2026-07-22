"""Small, explicit tokenizers for reproducible classroom calculations."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal


Tokenization = Literal["character", "whitespace", "tokens"]


def tokenize(value: str | Sequence[str], strategy: Tokenization) -> list[str]:
    if strategy == "tokens":
        if isinstance(value, str):
            raise ValueError("tokenization='tokens' requires a token list")
        return [token for token in value if token]
    if not isinstance(value, str):
        raise ValueError(f"tokenization={strategy!r} requires text input")
    if strategy == "character":
        return [character for character in value if not character.isspace()]
    if strategy == "whitespace":
        return re.findall(r"\S+", value)
    raise ValueError(f"unsupported tokenization strategy: {strategy}")
