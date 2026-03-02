"""
ClawBot Browser Bridge

Python wrapper for the Node.js browser sidecar. Manages the sidecar
process lifecycle and translates between the agent's tool interface
and the browser HTTP server.

The sidecar runs at server/agent/tools/browser/ and exposes:
  POST /execute  — run browser actions (navigate, click, fill_form, etc.)
  GET  /health   — readiness check

This bridge:
  1. Starts the sidecar on first use (lazy init)
  2. Health-checks before each call (auto-restarts if crashed)
  3. Translates ActionResult → ToolResult for the agentic loop
  4. Surfaces approval checkpoints so the LLM can pause for user consent

Design references:
  - OpenManus app/tool/browser_use_tool.py (lazy browser init, cleanup)
  - server/agent/tools/http_request.py (httpx patterns, self.success/fail)
  - server/agent/tools/tool_registry.py (BaseTool ABC, ToolResult)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

from server.agent.tools.tool_registry import BaseTool, ToolResult, truncate

logger = logging.getLogger(__name__)


class BrowserBridge(BaseTool):
    """Python wrapper for the Node.js browser sidecar.

    Manages the sidecar process lifecycle and translates
    between the agent's tool interface and the browser server.
    """

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._port: int = int(os.environ.get("CLAWBOT_BROWSER_PORT", "8090"))
        self._base_url: str = f"http://localhost:{self._port}"
        self._sidecar_dir: Path = Path(__file__).parent / "browser"
        self._startup_timeout: float = 30.0
        self._request_timeout: float = 45.0

    # ── BaseTool interface ────────────────────────────────────

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Automate browser interactions for websites without APIs. "
            "Use for web scraping, form filling, navigating sites, and extracting data. "
            "Every action returns a screenshot so you can see what happened. "
            "IMPORTANT: Payment pages, form submissions, CAPTCHAs, and 2FA pages "
            "require approval before proceeding — you will be notified when this happens."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "description": "The browser action to perform",
                "enum": [
                    "navigate",
                    "search",
                    "fill_form",
                    "click",
                    "extract_data",
                    "take_screenshot",
                    "get_page_content",
                ],
            },
            "params": {
                "type": "object",
                "required": True,
                "description": (
                    "Action-specific parameters. "
                    "navigate: {url}. "
                    "search: {site, query}. "
                    "fill_form: {fields: [{selector, value}]}. "
                    "click: {selector_or_text}. "
                    "extract_data: {selectors: [{name, selector}]}. "
                    "take_screenshot: {}. "
                    "get_page_content: {}."
                ),
            },
            "session_id": {
                "type": "string",
                "required": False,
                "description": (
                    "Optional session ID for isolated browser contexts. "
                    "Default: 'default'"
                ),
            },
        }

    async def execute(
        self,
        action: str = "",
        params: dict[str, Any] | None = None,
        session_id: str = "default",
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a browser action via the Node.js sidecar.

        Never raises — always returns a ToolResult.
        """
        if not action:
            return self.fail("Missing required parameter: action")
        if params is None:
            params = {}

        try:
            await self._ensure_sidecar_running()
        except RuntimeError as e:
            return self.fail(str(e))

        try:
            async with httpx.AsyncClient(timeout=self._request_timeout) as client:
                response = await client.post(
                    f"{self._base_url}/execute",
                    json={
                        "session_id": session_id,
                        "action": action,
                        "params": params,
                    },
                )

            result = response.json()

            # Handle checkpoint (needs_approval)
            if result.get("needs_approval"):
                checkpoint_info = json.dumps({
                    "needs_approval": True,
                    "reason": result.get("approval_reason", "Approval required"),
                    "checkpoint_type": result.get("checkpoint_type"),
                    "screenshot": result.get("screenshot", ""),
                })
                return ToolResult(
                    success=False,
                    output=checkpoint_info,
                    error=(
                        f"CHECKPOINT: {result.get('approval_reason')}. "
                        "Call request_approval before retrying."
                    ),
                )

            # Format output for the LLM
            output_data = result.get("result", {})
            output_text = json.dumps(output_data, indent=2, default=str)
            output_text = truncate(output_text, 20_000)

            if result.get("screenshot"):
                output_text += "\n\n[Screenshot captured — visible in tool result]"

            if result.get("success"):
                return self.success(output_text)

            return ToolResult(
                success=False,
                output=output_text,
                error=result.get("error", "Browser action failed"),
            )

        except httpx.TimeoutException:
            return self.fail(
                "Browser action timed out. The page may be loading slowly."
            )

        except httpx.ConnectError:
            # Mark process as dead so next call restarts it
            self._process = None
            return self.fail(
                "Could not connect to browser sidecar. "
                "It may have crashed. Retrying will restart it."
            )

        except Exception as e:
            logger.exception("Browser bridge error")
            return self.fail(f"Browser error: {e}")

    # ── Sidecar lifecycle ─────────────────────────────────────

    async def _ensure_sidecar_running(self) -> None:
        """Start the Node.js sidecar if it's not already running."""
        if self._process is not None and self._process.poll() is None:
            # Process alive — verify with health check
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"{self._base_url}/health")
                    if resp.status_code == 200:
                        return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass  # Not healthy, restart below

        # Kill stale process if any
        await self._stop_sidecar()

        # Start new sidecar process
        logger.info("Starting browser sidecar on port %d...", self._port)

        env = os.environ.copy()
        env["CLAWBOT_BROWSER_PORT"] = str(self._port)

        sidecar_dir = str(self._sidecar_dir)
        tsx_path = self._sidecar_dir / "node_modules" / ".bin" / "tsx"

        if tsx_path.exists():
            cmd = [str(tsx_path), "src/server.ts"]
        else:
            cmd = ["node", "dist/server.js"]

        self._process = subprocess.Popen(
            cmd,
            cwd=sidecar_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for health check to pass
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < self._startup_timeout:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(f"{self._base_url}/health")
                    if resp.status_code == 200:
                        logger.info(
                            "Browser sidecar started (pid=%d)", self._process.pid
                        )
                        return
            except (httpx.ConnectError, httpx.TimeoutException):
                pass

            # Check if process died during startup
            if self._process.poll() is not None:
                stderr = ""
                if self._process.stderr:
                    stderr = self._process.stderr.read().decode(errors="replace")
                await self._stop_sidecar()
                raise RuntimeError(
                    f"Browser sidecar exited during startup. stderr: {stderr[:500]}"
                )

            await asyncio.sleep(0.5)

        # Timeout
        await self._stop_sidecar()
        raise RuntimeError(
            f"Browser sidecar failed to start within {self._startup_timeout}s. "
            f"Ensure Node.js is installed and run: "
            f"cd {sidecar_dir} && npm install"
        )

    async def _stop_sidecar(self) -> None:
        """Stop the sidecar process if running."""
        if self._process is None:
            return

        try:
            self._process.terminate()
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=3)
        except Exception:
            pass
        finally:
            self._process = None
            logger.info("Browser sidecar stopped")

    async def shutdown(self) -> None:
        """Clean shutdown — call this when the agent stops."""
        await self._stop_sidecar()
