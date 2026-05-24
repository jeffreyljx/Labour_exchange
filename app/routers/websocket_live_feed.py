"""
WebSocket endpoints for live order book and trade-feed updates.

Clients connect to /ws/contracts/{contract_id} with their JWT passed as a
query parameter (?token=...) because browser WebSocket APIs do not support
custom headers.  The endpoint authenticates the token, then subscribes to the
Redis pubsub channel `ob:events:{contract_id}` and forwards every JSON message
to the connected client until the socket is closed.

Message shape published by the matching engine on each fill:
    {
        "type":        "trade",
        "contract_id": "<uuid>",
        "price":       "10.5000",
        "quantity":    50,
        "total_value": "525.0000",
        "timestamp":   "2026-05-21T12:34:56.789+00:00"
    }
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.config import settings
from app.services.security import _decode_token

router = APIRouter(tags=["websocket"])

_CHANNEL_PREFIX = "ob:events:"
_PING_INTERVAL = 30  # seconds between server-side keepalive pings


@router.websocket("/ws/contracts/{contract_id}")
async def contract_feed(
    websocket: WebSocket,
    contract_id: UUID,
    token: Optional[str] = Query(default=None),
) -> None:
    """
    Stream live trade-fill events for a contract.

    Authentication: pass JWT as ?token=<jwt>.  Unauthenticated connections are
    rejected with code 1008 (policy violation).
    """
    # -- Auth ----------------------------------------------------------------
    if token is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        _decode_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    channel = f"{_CHANNEL_PREFIX}{contract_id}"
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    # -- Redis pubsub runs in a background thread because redis-py's pubsub
    #    listener is blocking.  Messages are forwarded to the async queue. ----
    def _redis_listener() -> None:
        try:
            from app.redis_client import get_redis_client
            r = get_redis_client()
            pubsub = r.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(channel)
            for message in pubsub.listen():
                if message and message.get("type") == "message":
                    asyncio.run_coroutine_threadsafe(
                        queue.put(message["data"]), loop
                    )
                    # Sentinel check: if None is in the queue the socket closed.
                if queue.qsize() > 0:
                    item = None
                    try:
                        item = queue.get_nowait()
                        queue.task_done()
                    except Exception:
                        pass
                    if item is None:
                        break
                    # Re-enqueue the real message we accidentally consumed.
                    asyncio.run_coroutine_threadsafe(queue.put(item), loop)
        except Exception:
            pass
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    listener_thread = threading.Thread(target=_redis_listener, daemon=True)
    listener_thread.start()

    # -- Forward messages to the WebSocket client ----------------------------
    try:
        while True:
            try:
                # Wait up to PING_INTERVAL seconds for a pubsub message.
                message = await asyncio.wait_for(queue.get(), timeout=_PING_INTERVAL)
            except asyncio.TimeoutError:
                # Send a keepalive ping so the browser doesn't time out.
                await websocket.send_text(json.dumps({"type": "ping"}))
                continue

            if message is None:
                # Redis listener shut down (e.g. Redis disconnected).
                break

            await websocket.send_text(message)
            queue.task_done()

    except (WebSocketDisconnect, Exception):
        pass
    finally:
        # Signal the listener thread to stop by putting a sentinel.
        await queue.put(None)
