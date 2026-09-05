"""Seed officially verified Kimi, GLM, and Qwen-VL pricing rules."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

from dotenv import dotenv_values

from configs.settings import BASE_DIR
from server.quota.management import QuotaManagementService


PRICING_VERSION = "official-cny-2026-09-05"
EFFECTIVE_FROM = datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc)
CREDITS_MICRO_PER_CNY = 1_000_000
UNVERIFIED_PRICING_KEYS: tuple[str, ...] = ()

VERIFIED_RULES: tuple[dict[str, Any], ...] = (
    {
        # The image tool keeps requests below the first qwen3-vl-plus pricing
        # tier (<=32K input tokens). image_unit_credits_micro is only a
        # conservative admission hold; settlement replaces it with the
        # provider-reported image token count.
        "pricing_key": "qwen/qwen3-vl-plus",
        "ordinary_input_credits_micro_per_million_tokens": 1_000_000,
        "cached_input_credits_micro_per_million_tokens": 200_000,
        "cache_write_credits_micro_per_million_tokens": 1_250_000,
        "output_credits_micro_per_million_tokens": 10_000_000,
        "reasoning_output_credits_micro_per_million_tokens": None,
        "visual_input_credits_micro_per_million_tokens": 1_000_000,
        "image_unit_credits_micro": 2_048,
    },
    {
        "pricing_key": "kimi/kimi-k2.6",
        "ordinary_input_credits_micro_per_million_tokens": 6_500_000,
        "cached_input_credits_micro_per_million_tokens": 1_100_000,
        "cache_write_credits_micro_per_million_tokens": 6_500_000,
        "output_credits_micro_per_million_tokens": 27_000_000,
        "reasoning_output_credits_micro_per_million_tokens": None,
    },
    {
        "pricing_key": "glm/glm-5.3",
        "ordinary_input_credits_micro_per_million_tokens": 8_000_000,
        "cached_input_credits_micro_per_million_tokens": 2_000_000,
        "cache_write_credits_micro_per_million_tokens": 8_000_000,
        "output_credits_micro_per_million_tokens": 28_000_000,
        "reasoning_output_credits_micro_per_million_tokens": None,
    },
    {
        "pricing_key": "glm/glm-5.2",
        "ordinary_input_credits_micro_per_million_tokens": 8_000_000,
        "cached_input_credits_micro_per_million_tokens": 2_000_000,
        "cache_write_credits_micro_per_million_tokens": 8_000_000,
        "output_credits_micro_per_million_tokens": 28_000_000,
        "reasoning_output_credits_micro_per_million_tokens": None,
    },
)

_RATE_FIELDS = (
    "ordinary_input_credits_micro_per_million_tokens",
    "cached_input_credits_micro_per_million_tokens",
    "cache_write_credits_micro_per_million_tokens",
    "output_credits_micro_per_million_tokens",
    "reasoning_output_credits_micro_per_million_tokens",
    "visual_input_credits_micro_per_million_tokens",
    "image_unit_credits_micro",
    "search_call_credits_micro",
    "link_page_credits_micro",
)


def seed_verified_extended_model_pricing(
    database: str | Any,
    *,
    created_by: str,
) -> dict[str, Any]:
    """Create verified immutable rules, treating an exact rerun as idempotent."""
    service = QuotaManagementService(database)
    results: list[dict[str, Any]] = []
    try:
        for definition in VERIFIED_RULES:
            existing = next(
                (
                    row
                    for row in service.list_pricing_rules(
                        pricing_key=definition["pricing_key"]
                    )
                    if row["version"] == PRICING_VERSION
                ),
                None,
            )
            if existing is not None:
                mismatches = [
                    field
                    for field in _RATE_FIELDS
                    if existing[field] != definition.get(field)
                ]
                if mismatches:
                    raise RuntimeError(
                        f"pricing version conflict for {definition['pricing_key']}: "
                        f"{', '.join(mismatches)}"
                    )
                results.append(
                    {
                        "pricing_key": definition["pricing_key"],
                        "version": PRICING_VERSION,
                        "status": "already_present",
                    }
                )
                continue

            created = service.create_pricing_rule(
                **definition,
                version=PRICING_VERSION,
                effective_from=EFFECTIVE_FROM,
                effective_until=None,
                created_by=created_by,
            )
            results.append(
                {
                    "pricing_key": created["pricing_key"],
                    "version": created["version"],
                    "status": "created",
                }
            )
    finally:
        service.close()
    return {
        "currency": "CNY",
        "credits_micro_per_cny": CREDITS_MICRO_PER_CNY,
        "rules": results,
        "unverified_pricing_keys": list(UNVERIFIED_PRICING_KEYS),
    }


def _preview() -> dict[str, Any]:
    return {
        "currency": "CNY",
        "credits_micro_per_cny": CREDITS_MICRO_PER_CNY,
        "version": PRICING_VERSION,
        "effective_from": EFFECTIVE_FROM.isoformat(),
        "verified_rules": list(VERIFIED_RULES),
        "unverified_pricing_keys": list(UNVERIFIED_PRICING_KEYS),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed officially verified Kimi/GLM/Qwen-VL pricing rules."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the verified rules; without this flag, only print a preview.",
    )
    parser.add_argument("--created-by", default="p4-model-pricing")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(_preview(), ensure_ascii=False, indent=2))
        return

    database_url = str(
        os.environ.get("NLP_AGENT_DATABASE_URL")
        or dotenv_values(BASE_DIR / ".env").get("NLP_AGENT_DATABASE_URL")
        or ""
    ).strip()
    if not database_url:
        raise SystemExit("NLP_AGENT_DATABASE_URL is not configured")
    result = seed_verified_extended_model_pricing(
        database_url,
        created_by=args.created_by,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
