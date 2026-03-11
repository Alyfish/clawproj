"""
ClawBot Emit Alert Tool

Emit a watchlist alert event to iOS when a monitored condition
changes. Used by the agent after running a scheduled monitoring
check to notify the user of price drops, availability changes,
or other watch-worthy events.

Design references:
  - server/agent/tools/schedule.py (gateway-dependent tool pattern)
  - shared/types/gateway.ts (WatchlistAlertPayload, WatchlistAlertEvent)
  - server/agent/gateway_client.py (emit_watchlist_alert)
"""
from __future__ import annotations

import logging
from typing import Any

from server.agent.tools.tool_registry import BaseTool, ToolResult

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = (
    "watch_id",
    "alert_type",
    "title",
    "message",
    "item",
    "source",
    "previous_value",
    "current_value",
)


class EmitAlertTool(BaseTool):
    """Emit a watchlist alert to iOS when a monitored value changes."""

    def __init__(self, gateway_client: Any = None) -> None:
        self._gateway = gateway_client

    def set_gateway_client(self, client: Any) -> None:
        """Wire gateway client after initialization."""
        self._gateway = client

    @property
    def name(self) -> str:
        return "emit_alert"

    @property
    def description(self) -> str:
        return (
            "Send a watchlist alert to the user's phone when a monitored value changes. "
            "Use after a scheduled watch check detects a change (e.g. price drop, "
            "new availability, score update). Do NOT call on first run or when nothing changed."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "watch_id": {
                "type": "string",
                "required": True,
                "description": "The watch/job ID that triggered this alert.",
            },
            "alert_type": {
                "type": "string",
                "required": True,
                "enum": ["price_drop", "price_increase", "back_in_stock", "new_listing", "threshold_crossed", "general_change"],
                "description": "Category of the alert.",
            },
            "title": {
                "type": "string",
                "required": True,
                "description": "Short alert title shown in notification (e.g. 'RTX 5090 Price Drop').",
            },
            "message": {
                "type": "string",
                "required": True,
                "description": "Alert body with details (e.g. 'Dropped from $1,799 to $1,549 on StockX').",
            },
            "item": {
                "type": "string",
                "required": True,
                "description": "The item being monitored (e.g. 'RTX 5090', 'SFO-JFK flight').",
            },
            "source": {
                "type": "string",
                "required": True,
                "description": "Where the data came from (e.g. 'StockX', 'Google Flights').",
            },
            "previous_value": {
                "type": "string",
                "required": True,
                "description": "The previous value before the change.",
            },
            "current_value": {
                "type": "string",
                "required": True,
                "description": "The current value after the change.",
            },
            "threshold": {
                "type": "string",
                "required": False,
                "description": "The threshold that was crossed, if any.",
            },
            "url": {
                "type": "string",
                "required": False,
                "description": "Link to view the item (product page, listing URL).",
            },
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not self._gateway:
            return ToolResult(
                success=False,
                output="Gateway client not available. Cannot emit alerts.",
            )

        # Validate required fields
        for field in REQUIRED_FIELDS:
            if not kwargs.get(field):
                return ToolResult(
                    success=False,
                    output=f"Missing required field: {field}",
                )

        try:
            await self._gateway.emit_watchlist_alert(
                watch_id=kwargs["watch_id"],
                alert_type=kwargs["alert_type"],
                title=kwargs["title"],
                message=kwargs["message"],
                item=kwargs["item"],
                source=kwargs["source"],
                previous_value=str(kwargs["previous_value"]),
                current_value=str(kwargs["current_value"]),
                threshold=str(kwargs.get("threshold", "")),
                url=kwargs.get("url", ""),
            )
        except Exception as e:
            logger.error("emit_watchlist_alert failed: %s", e)
            return ToolResult(
                success=False,
                output=f"Failed to emit alert: {e}",
            )

        return ToolResult(
            success=True,
            output={
                "status": "alert_sent",
                "watch_id": kwargs["watch_id"],
                "alert_type": kwargs["alert_type"],
                "title": kwargs["title"],
            },
        )
