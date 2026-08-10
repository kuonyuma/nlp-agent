"""Backend Gateway Core public surface."""

from gateway.contracts import (
    GatewayEvent,
    GatewayEventType,
    GatewayHealth,
    InjectMessageRequest,
    SubmitTurnRequest,
    TurnAccepted,
    TurnRecord,
    TurnStatus,
)
from gateway.dispatch import InProcessTurnDispatcher, TurnDispatcher, TurnTask
from gateway.redis_transport import RedisTransportConfig, RedisTurnDispatcher

__all__ = [
    "GatewayEvent",
    "GatewayEventType",
    "GatewayHealth",
    "InjectMessageRequest",
    "SubmitTurnRequest",
    "TurnAccepted",
    "TurnRecord",
    "TurnStatus",
    "InProcessTurnDispatcher",
    "TurnDispatcher",
    "TurnTask",
    "RedisTransportConfig",
    "RedisTurnDispatcher",
]
