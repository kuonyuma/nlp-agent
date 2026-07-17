"""Inspect local observability data without starting a Web service."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.observability.service import global_observability_service
from core.identity import AuthenticatedPrincipal


async def run(args: argparse.Namespace) -> None:
    service = global_observability_service
    principal = AuthenticatedPrincipal.system_admin()
    if args.command == "overview":
        result = await service.overview(principal, args.days)
    elif args.command == "traces":
        result = await service.traces(
            principal,
            limit=args.limit, session_id=args.session_id, status=args.status
        )
    elif args.command == "trace":
        result = await service.trace(principal, args.trace_id)
    elif args.command == "sessions":
        result = await service.sessions(principal, args.days, args.limit)
    elif args.command == "usage":
        result = await service.usage(principal, args.days)
    elif args.command == "errors":
        result = await service.errors(principal, args.days, args.limit)
    elif args.command == "events":
        result = await service.events(
            principal,
            limit=args.limit, level=args.level, trace_id=args.trace_id
        )
    else:
        result = await service.health(principal)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Query NLP local telemetry")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("overview", "usage"):
        item = commands.add_parser(name)
        item.add_argument("--days", type=int, default=30)
    traces = commands.add_parser("traces")
    traces.add_argument("--limit", type=int, default=100)
    traces.add_argument("--session-id")
    traces.add_argument("--status")
    trace = commands.add_parser("trace")
    trace.add_argument("trace_id")
    sessions = commands.add_parser("sessions")
    sessions.add_argument("--days", type=int, default=30)
    sessions.add_argument("--limit", type=int, default=100)
    errors = commands.add_parser("errors")
    errors.add_argument("--days", type=int, default=30)
    errors.add_argument("--limit", type=int, default=100)
    events = commands.add_parser("events")
    events.add_argument("--limit", type=int, default=200)
    events.add_argument("--level")
    events.add_argument("--trace-id")
    commands.add_parser("health")
    return root


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
