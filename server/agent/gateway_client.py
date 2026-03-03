"""
ClawBot Gateway Client

WebSocket client connecting the Python agent to the ClawBot gateway.

Responsibilities:
- Connect with handshake (role: "node", scopes: ["agent"])
- Receive user messages as an async generator
- Emit structured events (stream text, thinking steps, tool activity, cards)
- Handle approval requests (block until user responds)
- Auto-reconnect with exponential backoff on disconnect

Protocol reference:
  - server/gateway/src/ws-server.ts (handshake, connection lifecycle)
  - server/gateway/src/message-router.ts (event routing, forwarding)
  - shared/types/gateway.ts (WSMessage, event types)
  - shared/types/approvals.ts (ApprovalAction, ApprovalRequest)
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# GATEWAY CLIENT
# ============================================================


class GatewayClient:
    """WebSocket client connecting the agent to the ClawBot gateway.

    The agent connects as role "node" with scope "agent".  The gateway
    forwards user messages as ``chat/message:new`` events.  The agent
    emits events (streaming tokens, tool activity, cards, approval
    requests) that are broadcast to all operators in the session.
    """

    def __init__(self, config: Any) -> None:
        self.config = config
        self._ws: ClientConnection | None = None
        self._connected: bool = False
        self._session_id: str | None = None
        self._device_token: str | None = None
        self._pending_approvals: dict[str, asyncio.Future[dict]] = {}
        self._reconnect_delay: float = config.reconnect_base_delay
        self._shutdown_event: asyncio.Event = asyncio.Event()

    # ── Connection Lifecycle ────────────────────────────────────

    async def connect(self) -> None:
        """Connect to gateway WebSocket and perform handshake."""
        url = self.config.gateway_url
        logger.info("Connecting to gateway at %s ...", url)

        self._ws = await websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
            max_size=10 * 1024 * 1024,  # 10 MB
        )
        self._connected = True
        self._reconnect_delay = self.config.reconnect_base_delay

        # Build handshake payload matching ConnectPayloadSchema
        # in server/gateway/src/ws-server.ts
        handshake: dict[str, Any] = {
            "type": "req",
            "id": str(uuid.uuid4()),
            "method": "connect",
            "payload": {
                "role": self.config.agent_role,
                "scopes": self.config.agent_scopes,
            },
        }
        # Include device token for session resumption if we have one
        if self._device_token:
            handshake["payload"]["deviceToken"] = self._device_token

        await self._send(handshake)
        logger.info("Gateway handshake sent")

        # Wait for handshake response (server has 10s timeout)
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=10.0)
            msg = json.loads(raw)
            payload = msg.get("payload", {})

            if msg.get("type") == "res" and "error" not in payload:
                self._session_id = payload.get("sessionId")
                self._device_token = payload.get("deviceToken")
                logger.info(
                    "Gateway connected, session=%s device=%s",
                    self._session_id,
                    self._device_token,
                )
            else:
                error = payload.get("error", "unknown")
                message = payload.get("message", "")
                logger.warning(
                    "Handshake error: %s — %s", error, message,
                )
        except asyncio.TimeoutError:
            logger.warning("Handshake response timeout — proceeding anyway")

    async def disconnect(self) -> None:
        """Disconnect from gateway and signal shutdown."""
        self._shutdown_event.set()
        if self._ws and self._ws.close_code is None:
            await self._ws.close()
        self._connected = False
        self._ws = None
        # Reject any pending approvals
        for approval_id, future in list(self._pending_approvals.items()):
            if not future.done():
                future.set_result({"approved": False, "message": "Disconnected"})
        self._pending_approvals.clear()
        logger.info("Disconnected from gateway")

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        self._connected = False
        self._ws = None
        while not self._shutdown_event.is_set():
            logger.info("Reconnecting in %.1fs ...", self._reconnect_delay)
            await asyncio.sleep(self._reconnect_delay)
            self._reconnect_delay = min(
                self._reconnect_delay * 2,
                self.config.reconnect_max_delay,
            )
            try:
                await self.connect()
                return
            except Exception as e:
                logger.warning("Reconnect failed: %s", e)

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket connection is active."""
        return self._connected and self._ws is not None and self._ws.close_code is None

    # ── Message Receiving ───────────────────────────────────────

    async def receive_messages(self) -> AsyncGenerator[dict, None]:
        """Async generator yielding incoming user messages.

        Each yielded dict::

            {
                "text": str,
                "session_id": str,
                "message_id": str,
                "attachments": list,
            }

        Also handles internally:
        - ``approval/resolved`` events → resolves pending futures
        - ``task/stop`` events → yields ``__STOP__`` sentinel
        - Reconnection on disconnect
        """
        while not self._shutdown_event.is_set():
            if not self.is_connected:
                try:
                    await self.connect()
                except Exception as e:
                    logger.error("Connection failed: %s", e)
                    await self._reconnect()
                    continue

            try:
                async for raw in self._ws:  # type: ignore[union-attr]
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Invalid JSON from gateway: %s",
                            str(raw)[:100],
                        )
                        continue

                    msg_type = msg.get("type")
                    event = msg.get("event")
                    payload = msg.get("payload", {})

                    # ── User chat message ────────────────────
                    if msg_type == "event" and event == "chat/message:new":
                        yield {
                            "text": payload.get("text", ""),
                            "session_id": payload.get("sessionId", "default"),
                            "message_id": str(uuid.uuid4()),
                            "attachments": payload.get("attachments", []),
                        }

                    # ── Approval resolved ────────────────────
                    elif msg_type == "event" and event == "approval/resolved":
                        approval_id = payload.get("approvalId")
                        if approval_id and approval_id in self._pending_approvals:
                            future = self._pending_approvals.pop(approval_id)
                            if not future.done():
                                decision = payload.get("decision", "denied")
                                future.set_result({
                                    "approved": decision == "approved",
                                    "message": "",
                                })

                    # ── Approval timeout ─────────────────────
                    elif msg_type == "event" and event == "approval/timeout":
                        approval_id = payload.get("approvalId")
                        if approval_id and approval_id in self._pending_approvals:
                            future = self._pending_approvals.pop(approval_id)
                            if not future.done():
                                future.set_result({
                                    "approved": False,
                                    "message": "Approval timed out",
                                })

                    # ── Task stop ────────────────────────────
                    elif msg_type == "event" and event == "task/stop":
                        yield {
                            "text": "__STOP__",
                            "session_id": payload.get(
                                "sessionId", "default",
                            ),
                            "message_id": "stop",
                            "attachments": [],
                        }

                    # ── Login events from iOS ─────────────────
                    elif msg_type == "event" and event in (
                        "login/input", "login/click", "login/done",
                    ):
                        yield {
                            "text": f"__LOGIN_{event.split('/')[1].upper()}__",
                            "session_id": payload.get("sessionId", "default"),
                            "message_id": str(uuid.uuid4()),
                            "attachments": [],
                            "login_event": event,
                            "login_payload": payload,
                        }

                    else:
                        logger.debug(
                            "Ignoring message: type=%s event=%s",
                            msg_type,
                            event,
                        )

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning("Gateway connection closed: %s", e)
                await self._reconnect()
            except Exception as e:
                logger.error("Error receiving messages: %s", e)
                await self._reconnect()

    # ── Event Emission ──────────────────────────────────────────

    async def _send(self, message: dict) -> None:
        """Send a raw JSON message over the WebSocket."""
        if not self.is_connected:
            return
        try:
            await self._ws.send(json.dumps(message))  # type: ignore[union-attr]
        except Exception as e:
            logger.warning("Failed to send: %s", e)

    async def emit_event(self, event: str, payload: dict) -> None:
        """Emit an event to the gateway (broadcast to operators)."""
        await self._send({"type": "event", "event": event, "payload": payload})

    async def stream_text(
        self, delta: str, session_id: str | None = None,
    ) -> None:
        """Stream a text delta to the user (one per token from Claude)."""
        await self.emit_event("agent/stream:assistant", {
            "delta": delta,
            "sessionId": session_id or self._session_id,
        })

    async def stream_lifecycle(
        self, status: str, run_id: str, session_id: str | None = None,
    ) -> None:
        """Signal start/end of an agent run."""
        await self.emit_event("agent/stream:lifecycle", {
            "status": status,
            "runId": run_id,
            "sessionId": session_id or self._session_id,
        })

    async def stream_thinking(
        self,
        tool_name: str,
        summary: str,
        status: str = "running",
        session_id: str | None = None,
    ) -> None:
        """Emit a thinking step (shows in ThinkingStepsContainer on iOS)."""
        await self.emit_event("chat/state:delta", {
            "thinkingStep": {
                "id": str(uuid.uuid4())[:8],
                "description": summary,
                "status": status,
                "toolName": tool_name,
                "timestamp": _iso_now(),
            },
            "sessionId": session_id or self._session_id,
        })

    async def emit_tool_start(
        self, tool_name: str, description: str, session_id: str | None = None,
    ) -> None:
        """Signal that a tool has started executing."""
        await self.emit_event("agent/tool:start", {
            "toolName": tool_name,
            "description": description,
            "sessionId": session_id or self._session_id,
        })

    async def emit_tool_end(
        self,
        tool_name: str,
        success: bool,
        summary: str,
        session_id: str | None = None,
    ) -> None:
        """Signal that a tool has finished executing."""
        await self.emit_event("agent/tool:end", {
            "toolName": tool_name,
            "success": success,
            "summary": summary,
            "sessionId": session_id or self._session_id,
        })

    async def emit_task_update(
        self,
        task_id: str,
        status: str,
        step: dict | None = None,
        card: dict | None = None,
    ) -> None:
        """Emit a task status update with optional step or card."""
        payload: dict[str, Any] = {"taskId": task_id, "status": status}
        if step:
            payload["step"] = step
        if card:
            payload["card"] = card
        await self.emit_event("task/update", payload)

    async def emit_card(self, card: dict) -> None:
        """Emit a card/created event to display a card on iOS."""
        await self.emit_event("card/created", {"card": card})

    async def emit_login_frame(self, frame_data: dict) -> None:
        """Emit a browser login frame (screenshot + elements). Ephemeral."""
        await self.emit_event("browser/login:frame", frame_data)

    async def emit_login_flow_end(
        self, profile: str, authenticated: bool, domain: str,
    ) -> None:
        """Signal login flow completed."""
        await self.emit_event("browser/login:end", {
            "profile": profile,
            "authenticated": authenticated,
            "domain": domain,
        })

    # ── Approval Flow ───────────────────────────────────────────

    async def request_approval(
        self,
        action: str,
        description: str,
        details: dict | None = None,
        timeout: float = 600.0,
    ) -> dict:
        """Request approval from the user. BLOCKS until resolved or timeout.

        Returns::

            {"approved": bool, "message": str}
        """
        approval_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict] = loop.create_future()
        self._pending_approvals[approval_id] = future

        await self._send({
            "type": "event",
            "event": "approval/requested",
            "payload": {
                "id": approval_id,
                "taskId": "",
                "action": action,
                "description": description,
                "details": details or {},
                "createdAt": _iso_now(),
            },
        })
        logger.info("Approval requested: %s — %s", action, description)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_approvals.pop(approval_id, None)
            return {"approved": False, "message": "Approval timed out"}


# ============================================================
# MOCK GATEWAY CLIENT (for test_mode)
# ============================================================


class MockGatewayClient:
    """Mock client for test mode.  Reads from stdin, writes to stdout.

    Has the same public method signatures as :class:`GatewayClient` so
    the agent code can use either without branching.
    """

    def __init__(self) -> None:
        self._session_id: str = "test-session"

    async def connect(self) -> None:
        print("[MockGateway] Connected (test mode — stdin/stdout)")

    async def disconnect(self) -> None:
        print("[MockGateway] Disconnected")

    @property
    def is_connected(self) -> bool:
        return True

    async def receive_messages(self) -> AsyncGenerator[dict, None]:
        """Read lines from stdin and yield them as user messages."""
        loop = asyncio.get_running_loop()
        while True:
            try:
                print("\n\U0001f9d1 You: ", end="", flush=True)
                line = await loop.run_in_executor(None, sys.stdin.readline)
                line = line.strip()
                if not line or line.lower() in ("quit", "exit", "/quit"):
                    return
                yield {
                    "text": line,
                    "session_id": "test-session",
                    "message_id": str(uuid.uuid4()),
                    "attachments": [],
                }
            except (EOFError, KeyboardInterrupt):
                return

    async def emit_event(self, event: str, payload: dict) -> None:
        pass  # no-op in test mode

    async def stream_text(
        self, delta: str, session_id: str | None = None,
    ) -> None:
        print(delta, end="", flush=True)

    async def stream_lifecycle(
        self, status: str, run_id: str, session_id: str | None = None,
    ) -> None:
        if status == "start":
            print("\n\U0001f916 ClawBot: ", end="", flush=True)
        elif status == "end":
            print()

    async def stream_thinking(
        self,
        tool_name: str,
        summary: str,
        status: str = "running",
        session_id: str | None = None,
    ) -> None:
        print(f"\n  \U0001f4ad [{tool_name}] {summary}", flush=True)

    async def emit_tool_start(
        self, tool_name: str, description: str, session_id: str | None = None,
    ) -> None:
        print(f"\n  \U0001f527 {description}...", end="", flush=True)

    async def emit_tool_end(
        self,
        tool_name: str,
        success: bool,
        summary: str,
        session_id: str | None = None,
    ) -> None:
        icon = "\u2705" if success else "\u274c"
        print(f" {icon} {summary}", flush=True)

    async def emit_task_update(
        self,
        task_id: str,
        status: str,
        step: dict | None = None,
        card: dict | None = None,
    ) -> None:
        print(f"\n  \U0001f4cb Task {task_id}: {status}")

    async def emit_card(self, card: dict) -> None:
        title = card.get("title", "untitled")
        card_type = card.get("type", "?")
        print(f"\n  \U0001f0cf Card: {title} ({card_type})")

    async def emit_login_frame(self, frame_data: dict) -> None:
        pass  # no-op in test mode

    async def emit_login_flow_end(
        self, profile: str, authenticated: bool, domain: str,
    ) -> None:
        icon = "\u2705" if authenticated else "\u274c"
        print(f"\n  {icon} Login flow ended: {domain} (authenticated={authenticated})")

    async def request_approval(
        self,
        action: str,
        description: str,
        details: dict | None = None,
        timeout: float = 600.0,
    ) -> dict:
        print(f"\n  \u26a0\ufe0f  APPROVAL REQUIRED ({action}): {description}")
        if details:
            print(f"     Details: {json.dumps(details, indent=2)}")
        print("     Approve? [y/N]: ", end="", flush=True)
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, sys.stdin.readline)
        approved = response.strip().lower() in ("y", "yes")
        return {"approved": approved, "message": "User responded in test mode"}
