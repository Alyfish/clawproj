"""
Tests for GatewayClient — background WS listener + message queue.

Covers:
- send_request() receives responses without deadlocking
- approval futures resolved by background listener
- Chat messages enqueued and yielded by receive_messages()
- Reconnect sentinel on connection close
- Disconnect drains queue and rejects pending futures
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.agent.gateway_client import GatewayClient


# ── Helpers ──────────────────────────────────────────────────


class FakeConfig:
    """Minimal config for GatewayClient."""
    gateway_url = "ws://fake:8080"
    agent_role = "node"
    agent_scopes = ["agent"]
    reconnect_base_delay = 0.01
    reconnect_max_delay = 0.05


class FakeWebSocket:
    """Fake WebSocket that supports async iteration and send/recv."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self.close_code = None
        self.sent: list[str] = []
        self._closed = False

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self, timeout: float | None = None) -> str:
        return await self._queue.get()

    def inject(self, msg: dict) -> None:
        """Push a message for the async iterator to yield."""
        self._queue.put_nowait(json.dumps(msg))

    async def close(self) -> None:
        self.close_code = 1000
        self._closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._closed:
            raise StopAsyncIteration
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            raise StopAsyncIteration


def _make_connected_client() -> tuple[GatewayClient, FakeWebSocket]:
    """Create a GatewayClient with a fake WS already connected."""
    client = GatewayClient(FakeConfig())
    ws = FakeWebSocket()
    client._ws = ws
    client._connected = True
    client._session_id = "test-session"
    return client, ws


# ── send_request() with background listener ─────────────────


@pytest.mark.asyncio
async def test_send_request_resolved_by_listener():
    """send_request() returns when the listener reads the matching `res`."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        # Fire send_request; the background listener will pick up the response
        req_id = None

        async def _capture_and_respond():
            """Wait for the request to be sent, then inject the response."""
            await asyncio.sleep(0.05)
            # Find the request ID from what was sent
            for raw in ws.sent:
                msg = json.loads(raw)
                if msg.get("method") == "schedule.create":
                    nonlocal req_id
                    req_id = msg["id"]
                    ws.inject({"type": "res", "id": req_id, "payload": {"ok": True}})
                    return

        responder = asyncio.create_task(_capture_and_respond())
        result = await asyncio.wait_for(
            client.send_request("schedule.create", {"cron": "0 */6 * * *"}),
            timeout=2.0,
        )
        await responder

        assert result == {"ok": True}
        assert req_id is not None
        assert req_id not in client._pending_requests  # cleaned up
    finally:
        client._stop_listener()


@pytest.mark.asyncio
async def test_send_request_timeout_still_works():
    """send_request() times out if no response arrives (no deadlock)."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        result = await client.send_request("schedule.list", {}, timeout=0.2)
        assert "error" in result
        assert result["error"] == "TIMEOUT"
    finally:
        client._stop_listener()


# ── Approval futures resolved by listener ────────────────────


@pytest.mark.asyncio
async def test_approval_resolved_by_listener():
    """approval/resolved events resolve pending approval futures."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        approval_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict] = loop.create_future()
        client._pending_approvals[approval_id] = future

        # Inject the approval resolution
        ws.inject({
            "type": "event",
            "event": "approval/resolved",
            "payload": {"approvalId": approval_id, "decision": "approved"},
        })

        result = await asyncio.wait_for(future, timeout=1.0)
        assert result["approved"] is True
        assert approval_id not in client._pending_approvals
    finally:
        client._stop_listener()


@pytest.mark.asyncio
async def test_approval_timeout_by_listener():
    """approval/timeout events resolve pending approval futures."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        approval_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict] = loop.create_future()
        client._pending_approvals[approval_id] = future

        ws.inject({
            "type": "event",
            "event": "approval/timeout",
            "payload": {"approvalId": approval_id},
        })

        result = await asyncio.wait_for(future, timeout=1.0)
        assert result["approved"] is False
        assert "timed out" in result["message"].lower()
    finally:
        client._stop_listener()


# ── Chat messages enqueued ───────────────────────────────────


@pytest.mark.asyncio
async def test_chat_message_enqueued():
    """Chat messages go through the queue to receive_messages()."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        ws.inject({
            "type": "event",
            "event": "chat/message:new",
            "payload": {"text": "hello", "sessionId": "s1"},
        })

        # The message should appear in the queue
        msg = await asyncio.wait_for(client._message_queue.get(), timeout=1.0)
        assert msg["type"] == "event"
        assert msg["event"] == "chat/message:new"
        assert msg["payload"]["text"] == "hello"
    finally:
        client._stop_listener()


@pytest.mark.asyncio
async def test_schedule_trigger_enqueued():
    """Schedule trigger events pass through to the queue (not consumed by listener)."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        ws.inject({
            "type": "event",
            "event": "schedule/task:trigger",
            "payload": {"sessionId": "s1", "jobId": "j1"},
        })

        msg = await asyncio.wait_for(client._message_queue.get(), timeout=1.0)
        assert msg["event"] == "schedule/task:trigger"
    finally:
        client._stop_listener()


# ── Disconnect cleanup ───────────────────────────────────────


@pytest.mark.asyncio
async def test_disconnect_rejects_pending_requests():
    """disconnect() rejects all pending request futures."""
    client, ws = _make_connected_client()

    loop = asyncio.get_running_loop()
    future: asyncio.Future[dict] = loop.create_future()
    client._pending_requests["req-1"] = future

    await client.disconnect()

    assert future.done()
    result = future.result()
    assert result.get("error") == "DISCONNECTED"
    assert len(client._pending_requests) == 0


@pytest.mark.asyncio
async def test_disconnect_rejects_pending_approvals():
    """disconnect() rejects all pending approval futures."""
    client, ws = _make_connected_client()

    loop = asyncio.get_running_loop()
    future: asyncio.Future[dict] = loop.create_future()
    client._pending_approvals["appr-1"] = future

    await client.disconnect()

    assert future.done()
    result = future.result()
    assert result["approved"] is False
    assert len(client._pending_approvals) == 0


@pytest.mark.asyncio
async def test_disconnect_stops_listener():
    """disconnect() cancels the background listener task."""
    client, ws = _make_connected_client()
    client._start_listener()
    assert client._listener_task is not None

    await client.disconnect()
    # Give the event loop a tick to process the cancellation
    await asyncio.sleep(0.01)

    assert client._listener_task is None or client._listener_task.done()


# ── Concurrent send_request + message flow ───────────────────


@pytest.mark.asyncio
async def test_concurrent_send_request_and_chat():
    """send_request() and chat messages work concurrently (the original bug)."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        # Inject a chat message AND a response interleaved
        ws.inject({
            "type": "event",
            "event": "chat/message:new",
            "payload": {"text": "user msg", "sessionId": "s1"},
        })

        async def _delayed_send_and_respond():
            await asyncio.sleep(0.05)
            result = await client.send_request("schedule.list", {}, timeout=1.0)
            return result

        # Start the send_request in background
        send_task = asyncio.create_task(_delayed_send_and_respond())

        # Wait a moment then inject the response
        await asyncio.sleep(0.1)
        for raw in ws.sent:
            msg = json.loads(raw)
            if msg.get("method") == "schedule.list":
                ws.inject({"type": "res", "id": msg["id"], "payload": {"jobs": []}})
                break

        # Both should complete
        chat_msg = await asyncio.wait_for(client._message_queue.get(), timeout=1.0)
        assert chat_msg["payload"]["text"] == "user msg"

        result = await asyncio.wait_for(send_task, timeout=2.0)
        assert result == {"jobs": []}
    finally:
        client._stop_listener()


# ── Credential request/response futures ──────────────────────


@pytest.mark.asyncio
async def test_credential_response_resolved_by_listener():
    """credential/response events resolve pending credential futures."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict | None] = loop.create_future()
        client._pending_credentials[request_id] = future

        ws.inject({
            "type": "event",
            "event": "credential/response",
            "payload": {
                "requestId": request_id,
                "domain": "example.com",
                "credentials": [{"username": "u", "password": "p"}],
            },
        })

        result = await asyncio.wait_for(future, timeout=1.0)
        assert result is not None
        assert result["credentials"][0]["username"] == "u"
        assert request_id not in client._pending_credentials
    finally:
        client._stop_listener()


@pytest.mark.asyncio
async def test_credential_none_resolved_by_listener():
    """credential/none events resolve pending credential futures to None."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict | None] = loop.create_future()
        client._pending_credentials[request_id] = future

        ws.inject({
            "type": "event",
            "event": "credential/none",
            "payload": {
                "requestId": request_id,
                "domain": "example.com",
                "reason": "user_denied",
            },
        })

        result = await asyncio.wait_for(future, timeout=1.0)
        assert result is None
        assert request_id not in client._pending_credentials
    finally:
        client._stop_listener()


@pytest.mark.asyncio
async def test_credential_events_not_enqueued():
    """Credential events are consumed by listener, not put in message queue."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict | None] = loop.create_future()
        client._pending_credentials[request_id] = future

        ws.inject({
            "type": "event",
            "event": "credential/response",
            "payload": {"requestId": request_id, "domain": "x.com", "credentials": []},
        })

        await asyncio.wait_for(future, timeout=1.0)

        # Also inject a chat message to verify the queue is working
        ws.inject({
            "type": "event",
            "event": "chat/message:new",
            "payload": {"text": "hello"},
        })

        msg = await asyncio.wait_for(client._message_queue.get(), timeout=1.0)
        assert msg["event"] == "chat/message:new"
        # Queue should only have the chat message, not the credential event
        assert client._message_queue.empty()
    finally:
        client._stop_listener()


@pytest.mark.asyncio
async def test_disconnect_rejects_pending_credentials():
    """disconnect() rejects all pending credential futures to None."""
    client, ws = _make_connected_client()

    loop = asyncio.get_running_loop()
    future: asyncio.Future[dict | None] = loop.create_future()
    client._pending_credentials["cred-1"] = future

    await client.disconnect()

    assert future.done()
    result = future.result()
    assert result is None
    assert len(client._pending_credentials) == 0


@pytest.mark.asyncio
async def test_request_credentials_method():
    """request_credentials() emits event and waits for response."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        async def _respond():
            await asyncio.sleep(0.05)
            for raw in ws.sent:
                msg = json.loads(raw)
                if msg.get("event") == "credential/request":
                    request_id = msg["payload"]["requestId"]
                    ws.inject({
                        "type": "event",
                        "event": "credential/response",
                        "payload": {
                            "requestId": request_id,
                            "domain": "test.com",
                            "credentials": [{"username": "u", "password": "p"}],
                        },
                    })
                    return

        responder = asyncio.create_task(_respond())
        result = await asyncio.wait_for(
            client.request_credentials("test.com", "reason"),
            timeout=2.0,
        )
        await responder

        assert result is not None
        assert result["credentials"][0]["username"] == "u"
    finally:
        client._stop_listener()


# ── OAuth token delivery ────────────────────────────────────


@pytest.mark.asyncio
async def test_credential_token_sets_env():
    """credential/token events set os.environ and store in _oauth_tokens."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        ws.inject({
            "type": "event",
            "event": "credential/token",
            "payload": {"service": "google", "token": "test-token-123", "sessionId": "s1"},
        })
        await asyncio.sleep(0.1)

        assert client._oauth_tokens.get("google") == "test-token-123"
        assert os.environ.get("GOOGLE_WORKSPACE_CLI_TOKEN") == "test-token-123"
    finally:
        client._stop_listener()
        os.environ.pop("GOOGLE_WORKSPACE_CLI_TOKEN", None)


@pytest.mark.asyncio
async def test_credential_token_resolves_refresh_future():
    """credential/token resolves a pending token refresh future."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str | None] = loop.create_future()
        client._pending_token_refreshes["google"] = future

        ws.inject({
            "type": "event",
            "event": "credential/token",
            "payload": {"service": "google", "token": "refreshed-token", "sessionId": "s1"},
        })

        result = await asyncio.wait_for(future, timeout=1.0)
        assert result == "refreshed-token"
        assert "google" not in client._pending_token_refreshes
    finally:
        client._stop_listener()
        os.environ.pop("GOOGLE_WORKSPACE_CLI_TOKEN", None)


@pytest.mark.asyncio
async def test_credential_token_not_enqueued():
    """credential/token events are consumed by listener, not put in message queue."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        ws.inject({
            "type": "event",
            "event": "credential/token",
            "payload": {"service": "google", "token": "t", "sessionId": "s1"},
        })
        # Also inject a chat message
        ws.inject({
            "type": "event",
            "event": "chat/message:new",
            "payload": {"text": "hello"},
        })

        msg = await asyncio.wait_for(client._message_queue.get(), timeout=1.0)
        assert msg["event"] == "chat/message:new"
        assert client._message_queue.empty()
    finally:
        client._stop_listener()
        os.environ.pop("GOOGLE_WORKSPACE_CLI_TOKEN", None)


@pytest.mark.asyncio
async def test_request_token_refresh_emits_expired_event():
    """request_token_refresh emits credential/token:expired and waits."""
    client, ws = _make_connected_client()
    client._start_listener()

    try:
        async def _respond():
            await asyncio.sleep(0.05)
            ws.inject({
                "type": "event",
                "event": "credential/token",
                "payload": {"service": "google", "token": "new-token", "sessionId": "s1"},
            })

        responder = asyncio.create_task(_respond())
        result = await asyncio.wait_for(
            client.request_token_refresh("google"),
            timeout=2.0,
        )
        await responder

        assert result == "new-token"
        # Verify the expired event was emitted
        expired_events = [
            json.loads(m) for m in ws.sent
            if "credential/token:expired" in m
        ]
        assert len(expired_events) >= 1
        assert expired_events[0]["payload"]["service"] == "google"
    finally:
        client._stop_listener()
        os.environ.pop("GOOGLE_WORKSPACE_CLI_TOKEN", None)


@pytest.mark.asyncio
async def test_disconnect_rejects_pending_token_refreshes():
    """disconnect() rejects pending token refresh futures to None."""
    client, ws = _make_connected_client()

    loop = asyncio.get_running_loop()
    future: asyncio.Future[str | None] = loop.create_future()
    client._pending_token_refreshes["google"] = future

    await client.disconnect()

    assert future.done()
    assert future.result() is None
    assert len(client._pending_token_refreshes) == 0
