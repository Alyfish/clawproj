"""
ClawBot Schedule Tool

Create, list, pause, resume, or remove scheduled watches for
autonomous monitoring. Watches fire on a cron schedule and run
a skill (default: price-monitor) to check conditions.

Design references:
  - gateway scheduler.ts (schedule.create / .list / .remove / .pause / .resume)
  - .claude/skills/price-monitor/SKILL.md (monitoring skill)
  - shared/types/gateway.ts (SchedulerEvent types)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from server.agent.tools.tool_registry import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# ── Interval presets ─────────────────────────────────────────────────
# Human-friendly names that map to cron expressions.
# Agent can pass a preset key OR a raw cron expression.

INTERVAL_PRESETS: dict[str, str] = {
    "every_5_minutes": "*/5 * * * *",
    "every_15_minutes": "*/15 * * * *",
    "every_hour": "0 * * * *",
    "every_6_hours": "0 */6 * * *",
    "daily_morning": "0 9 * * *",
    "daily_evening": "0 18 * * *",
    "weekly": "0 9 * * 1",
}


class ScheduleTool(BaseTool):
    """Create, list, pause, resume, or remove scheduled watches."""

    def __init__(self, gateway_client: Any = None) -> None:
        self._gateway = gateway_client

    def set_gateway_client(self, client: Any) -> None:
        """Wire gateway client after initialization."""
        self._gateway = client

    @property
    def name(self) -> str:
        return "schedule"

    @property
    def description(self) -> str:
        return (
            "Manage scheduled watches for autonomous monitoring. "
            "Actions: create_watch, list_watches, remove_watch, pause_watch, resume_watch. "
            "Use create_watch when the user says 'watch this', 'monitor that', or 'alert me when'. "
            "Presets: every_hour, every_6_hours, daily_morning, daily_evening, weekly."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "enum": [
                    "create_watch",
                    "list_watches",
                    "remove_watch",
                    "pause_watch",
                    "resume_watch",
                ],
                "description": "The scheduling action to perform.",
            },
            "description": {
                "type": "string",
                "required": False,
                "description": "Human-readable description of what to watch.",
            },
            "interval": {
                "type": "string",
                "required": False,
                "description": (
                    "Preset name (every_hour, every_6_hours, daily_morning, "
                    "daily_evening, weekly) or a raw cron expression. "
                    "Default: every_6_hours."
                ),
            },
            "check_instructions": {
                "type": "string",
                "required": False,
                "description": "Instructions for what to check when the watch fires.",
            },
            "skill_name": {
                "type": "string",
                "required": False,
                "description": "Skill to load when the watch fires (default: price-monitor).",
            },
            "payload": {
                "type": "object",
                "required": False,
                "description": "Structured data to pass to the skill on each run.",
            },
            "watch_id": {
                "type": "string",
                "required": False,
                "description": "Watch ID for remove, pause, or resume actions.",
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        action = kwargs.get("action", "")

        if not self._gateway:
            return ToolResult(
                success=False,
                output="Gateway client not available. Cannot manage watches.",
            )

        if action == "create_watch":
            return await self._create_watch(kwargs)
        elif action == "list_watches":
            return await self._list_watches()
        elif action == "remove_watch":
            return await self._remove_watch(kwargs.get("watch_id", ""))
        elif action == "pause_watch":
            return await self._pause_watch(kwargs.get("watch_id", ""))
        elif action == "resume_watch":
            return await self._resume_watch(kwargs.get("watch_id", ""))
        else:
            return ToolResult(success=False, output=f"Unknown action: {action}")

    # ── Private action handlers ──────────────────────────────────────

    async def _create_watch(self, kwargs: dict[str, Any]) -> ToolResult:
        description = kwargs.get("description", "")
        check_instructions = kwargs.get("check_instructions", "")

        if not description:
            return ToolResult(
                success=False,
                output="Missing required field: description",
            )
        if not check_instructions:
            return ToolResult(
                success=False,
                output="Missing required field: check_instructions",
            )

        # Resolve interval: preset key -> cron expression, or pass through as-is
        raw_interval = kwargs.get("interval", "every_6_hours")
        cron_expression = INTERVAL_PRESETS.get(raw_interval, raw_interval)

        skill_name = kwargs.get("skill_name", "price-monitor")
        payload = kwargs.get("payload") or {}

        try:
            response = await self._gateway.send_request(
                "schedule.create",
                {
                    "cronExpression": cron_expression,
                    "skillName": skill_name,
                    "taskDescription": description,
                    "checkInstructions": check_instructions,
                    "payload": payload,
                },
            )
        except Exception as e:
            logger.error("schedule.create failed: %s", e)
            return ToolResult(success=False, output=f"Failed to create watch: {e}")

        if "error" in response:
            return ToolResult(
                success=False,
                output=response.get("message", response["error"]),
            )

        job_id = response.get("jobId", "unknown")
        next_run = response.get("nextRun", "unknown")

        return ToolResult(
            success=True,
            output=(
                f"Watch created (ID: {job_id}). "
                f"Will check {raw_interval} ({cron_expression}). "
                f"Next run: {next_run}"
            ),
        )

    async def _list_watches(self) -> ToolResult:
        try:
            response = await self._gateway.send_request("schedule.list", {})
        except Exception as e:
            logger.error("schedule.list failed: %s", e)
            return ToolResult(success=False, output=f"Failed to list watches: {e}")

        if "error" in response:
            return ToolResult(
                success=False,
                output=response.get("message", response["error"]),
            )

        jobs = response.get("jobs", [])
        if not jobs:
            return ToolResult(success=True, output="No active watches.")

        lines = [f"{'ID':<12} {'Description':<30} {'Interval':<20} {'Active':<8} {'Last Checked':<22} {'Next Run'}"]
        lines.append("-" * 110)
        for job in jobs:
            lines.append(
                f"{job.get('id', '?'):<12} "
                f"{job.get('taskDescription', '?')[:28]:<30} "
                f"{job.get('cronExpression', '?'):<20} "
                f"{'yes' if job.get('active', True) else 'paused':<8} "
                f"{job.get('lastChecked', 'never'):<22} "
                f"{job.get('nextRun', '?')}"
            )

        return ToolResult(success=True, output="\n".join(lines))

    async def _remove_watch(self, watch_id: str) -> ToolResult:
        if not watch_id:
            return ToolResult(
                success=False,
                output="Missing required field: watch_id",
            )

        try:
            response = await self._gateway.send_request(
                "schedule.remove", {"watchId": watch_id}
            )
        except Exception as e:
            logger.error("schedule.remove failed: %s", e)
            return ToolResult(success=False, output=f"Failed to remove watch: {e}")

        if "error" in response:
            return ToolResult(
                success=False,
                output=response.get("message", response["error"]),
            )

        return ToolResult(success=True, output=f"Watch {watch_id} removed.")

    async def _pause_watch(self, watch_id: str) -> ToolResult:
        if not watch_id:
            return ToolResult(
                success=False,
                output="Missing required field: watch_id",
            )

        try:
            response = await self._gateway.send_request(
                "schedule.pause", {"watchId": watch_id}
            )
        except Exception as e:
            logger.error("schedule.pause failed: %s", e)
            return ToolResult(success=False, output=f"Failed to pause watch: {e}")

        if "error" in response:
            return ToolResult(
                success=False,
                output=response.get("message", response["error"]),
            )

        return ToolResult(success=True, output=f"Watch {watch_id} paused.")

    async def _resume_watch(self, watch_id: str) -> ToolResult:
        if not watch_id:
            return ToolResult(
                success=False,
                output="Missing required field: watch_id",
            )

        try:
            response = await self._gateway.send_request(
                "schedule.resume", {"watchId": watch_id}
            )
        except Exception as e:
            logger.error("schedule.resume failed: %s", e)
            return ToolResult(success=False, output=f"Failed to resume watch: {e}")

        if "error" in response:
            return ToolResult(
                success=False,
                output=response.get("message", response["error"]),
            )

        return ToolResult(success=True, output=f"Watch {watch_id} resumed.")
