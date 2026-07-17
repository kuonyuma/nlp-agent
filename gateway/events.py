"""In-process live delivery backed by the durable Gateway event log."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from gateway.contracts import GatewayEvent


@dataclass(slots=True)
class _Subscription:
    queue: asyncio.Queue[GatewayEvent]
    turn_id: str | None
    session_id: str | None


class GatewayEventBroker:
    def __init__(self) -> None:
        self._subscriptions: dict[int, _Subscription] = {}
        self._next_id = 1

    def subscribe(
        self,
        *,
        turn_id: str | None = None,
        session_id: str | None = None,
        maxsize: int = 500,
    ) -> tuple[int, asyncio.Queue[GatewayEvent]]:
        if turn_id is None and session_id is None:
            raise ValueError("turn_id or session_id is required")
        queue: asyncio.Queue[GatewayEvent] = asyncio.Queue(maxsize=maxsize)
        subscription_id = self._next_id
        self._next_id += 1
        self._subscriptions[subscription_id] = _Subscription(queue, turn_id, session_id)
        return subscription_id, queue

    def unsubscribe(self, subscription_id: int) -> None:
        self._subscriptions.pop(subscription_id, None)

    def publish(self, event: GatewayEvent) -> int:
        dropped = 0
        for subscription in tuple(self._subscriptions.values()):
            if subscription.turn_id is not None and subscription.turn_id != event.turn_id:
                continue
            if subscription.session_id is not None and subscription.session_id != event.session_id:
                continue
            try:
                subscription.queue.put_nowait(event)
            except asyncio.QueueFull:
                dropped += 1
        return dropped

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)
