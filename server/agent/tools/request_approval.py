"""
ClawBot Request Approval Tool

Gates risky actions behind user approval. REQUIRED before any
payment, form submission, message sending, deletion, or sharing
personal info.

Design references:
  - OpenManus Terminate (delegates to system, returns status)
  - .claude/skills/approval-safety/SKILL.md (always-ask actions)
  - shared/types/approvals.ts (ApprovalAction, ApprovalRequest)
  - gateway-protocol SKILL.md (approval/requested event)
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from server.agent.tools.tool_registry import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class GatewayClient(Protocol):
    """Gateway client interface for approval requests."""

    async def emit_event(
        self, event: str, payload: dict
    ) -> None: ...

    async def request_approval(
        self, action: str, description: str, details: dict
    ) -> dict: ...


class RequestApprovalTool(BaseTool):
    """Request user approval before executing a risky action.

    REQUIRED before any payment, form submission, message sending,
    deletion, or sharing personal info. Matches the always-ask
    actions defined in approval-safety SKILL.md and
    shared/types/approvals.ts.
    """

    def __init__(
        self, gateway_client: Optional[Any] = None
    ) -> None:
        self._gateway_client = gateway_client

    @property
    def name(self) -> str:
        return "request_approval"

    @property
    def description(self) -> str:
        return (
            "Request user approval before executing a risky action. "
            "REQUIRED before any payment, form submission, message "
            "sending, deletion, or sharing personal info."
        )

    @property
    def requires_approval(self) -> list[str]:
        """All always-ask actions from approval-safety SKILL.md."""
        return ["submit", "pay", "send", "delete", "share_personal_info"]

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "description": (
                    "Action requiring approval (e.g., 'book_flight', "
                    "'send_email', 'delete_file')"
                ),
            },
            "description": {
                "type": "string",
                "required": True,
                "description": (
                    "Human-readable explanation of what will happen"
                ),
            },
            "details": {
                "type": "object",
                "required": False,
                "description": "Additional context for the user",
            },
        }

    async def execute(
        self,
        action: str = "",
        description: str = "",
        details: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Request approval for a risky action.

        Args:
            action: Action type (e.g., "book_flight", "send_email")
            description: Human-readable explanation
            details: Optional additional context

        Returns:
            ToolResult with {approved: bool, message?: str}.
            Safe default: denied if gateway unavailable or errors.
        """
        if self._gateway_client is None:
            return self.fail(
                "Approval system not configured. "
                "Cannot proceed with risky actions without user approval."
            )

        if not action:
            return self.fail("Missing required parameter: action")
        if not description:
            return self.fail("Missing required parameter: description")

        try:
            result = await self._gateway_client.request_approval(
                action, description, details or {}
            )
            approved = result.get("approved", False)
            message = result.get("message")

            logger.info(
                "Approval request: action=%s approved=%s",
                action, approved,
            )

            return self.success({
                "approved": approved,
                "message": message,
            })

        except Exception as e:
            # Safe default: deny on error
            logger.warning(
                "Approval request failed: action=%s error=%s", action, e
            )
            return self.success({
                "approved": False,
                "message": f"Approval request failed: {e}",
            })
