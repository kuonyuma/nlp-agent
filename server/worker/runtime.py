"""Redis-backed independent Worker lifecycle."""

from __future__ import annotations

import asyncio
import socket

from configs.settings import settings
from gateway.contracts import GatewayEventType, TurnStatus
from gateway.engine import LangGraphAgentEngine
from gateway.redis_transport import (
    RedisEventPublisher,
    RedisTransportConfig,
    RedisWorkerRuntime,
)
from gateway.state_factory import build_turn_execution_state
from gateway.turn_execution import InProcessTurnExecutor
from server.infrastructure.mysql import MySQLRuntime


def redis_config() -> RedisTransportConfig:
    config = settings.gateway_runtime
    return RedisTransportConfig(
        url=str(config.get("redis_url", "redis://127.0.0.1:6379/0")),
        task_stream=str(config.get("redis_turn_stream", "nlp-agent:turns")),
        task_group=str(config.get("redis_turn_group", "nlp-agent-workers")),
        event_channel=str(config.get("redis_event_channel", "nlp-agent:events")),
        control_channel=str(config.get("redis_control_channel", "nlp-agent:control")),
        reclaim_idle_ms=int(config.get("redis_reclaim_idle_ms", 60_000)),
        cancel_key_prefix=str(
            config.get("redis_cancel_key_prefix", "nlp-agent:cancel:")
        ),
        cancel_ttl_s=int(config.get("redis_cancel_ttl_s", 604_800)),
        dead_letter_stream=str(
            config.get("redis_dead_letter_stream", "nlp-agent:turns:dead")
        ),
    )


async def run_worker() -> None:
    from redis.asyncio import Redis

    database_runtime = MySQLRuntime.from_runtime(settings.database_runtime)
    await database_runtime.start()
    config = redis_config()
    redis = Redis.from_url(config.url, decode_responses=True)
    gateway_config = settings.gateway_runtime
    repository = build_turn_execution_state(gateway_config)
    engine = LangGraphAgentEngine()
    publisher = RedisEventPublisher(redis, config)

    async def emit(turn_id: str, session_id: str, event_type: GatewayEventType, payload: dict) -> None:
        event = await asyncio.to_thread(
            repository.append_event,
            turn_id=turn_id,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
        )
        await publisher.publish(event)

    async def cancel_pending(task) -> None:
        turn = await asyncio.to_thread(repository.get_turn, task.turn_id)
        if turn is None:
            raise LookupError(f"turn state is unavailable: {task.turn_id}")
        if turn.status != TurnStatus.CANCELLED:
            await asyncio.to_thread(
                repository.update_turn, task.turn_id, TurnStatus.CANCELLED
            )
        event = await asyncio.to_thread(
            repository.ensure_event,
            turn_id=task.turn_id,
            session_id=task.context.session_id,
            event_type=GatewayEventType.TURN_CANCELLED,
            payload={"status": TurnStatus.CANCELLED.value},
        )
        await publisher.publish(event)

    async def is_terminal(task) -> bool:
        turn = await asyncio.to_thread(repository.get_turn, task.turn_id)
        if turn is None:
            raise LookupError(f"turn state is unavailable: {task.turn_id}")
        if turn.status == TurnStatus.COMPLETED:
            terminal_events = (
                (GatewayEventType.MESSAGE_COMPLETED, {"content": turn.final_text or ""}),
                (
                    GatewayEventType.TURN_COMPLETED,
                    {
                        "status": TurnStatus.COMPLETED.value,
                        "content": turn.final_text or "",
                    },
                ),
            )
        elif turn.status == TurnStatus.CANCELLED:
            terminal_events = ((
                GatewayEventType.TURN_CANCELLED,
                {"status": TurnStatus.CANCELLED.value},
            ),)
        elif turn.status in {TurnStatus.FAILED, TurnStatus.INTERRUPTED}:
            terminal_events = ((
                GatewayEventType.TURN_FAILED,
                {
                    "status": turn.status.value,
                    "error_kind": turn.error_kind or "worker_interrupted",
                    "message": turn.error_message or "",
                },
            ),)
        else:
            return False
        for event_type, payload in terminal_events:
            event = await asyncio.to_thread(
                repository.ensure_event,
                turn_id=task.turn_id,
                session_id=task.context.session_id,
                event_type=event_type,
                payload=payload,
            )
            await publisher.publish(event)
        return True

    await engine.start(emit)
    executor = InProcessTurnExecutor(engine, repository, emit)
    worker = RedisWorkerRuntime(
        redis,
        config,
        executor.run,
        consumer_name=f"{socket.gethostname()}-{id(executor)}",
        inject=engine.inject,
        cancel_pending=cancel_pending,
        is_terminal=is_terminal,
    )
    try:
        await worker.run_forever()
    finally:
        await worker.close()
        await engine.close()
        repository.close()
        await redis.aclose()
        await database_runtime.close()
