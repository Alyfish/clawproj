"""
ClawBot Create Card Tool

Creates rich cards (flight, house, pick, doc, or custom) and emits
them to the iOS client via the gateway.

Design references:
  - OpenManus Terminate (simple tool that signals system, not compute)
  - shared/types/cards.ts BaseCard (id, type, title, subtitle, metadata,
    actions, ranking, source, createdAt)
  - .claude/skills/card-schemas/SKILL.md (card types, ranking labels)
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol

from server.agent.tools.tool_registry import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class GatewayClient(Protocol):
    """Gateway client interface for emitting events to the iOS client."""

    async def emit_event(self, event: str, payload: dict) -> None: ...


class CreateCardTool(BaseTool):
    """Create a rich card to display structured results to the user.

    Cards appear as interactive UI elements in the iOS app.
    Card shape matches BaseCard from shared/types/cards.ts.
    """

    def __init__(
        self, gateway_client: Optional[Any] = None
    ) -> None:
        self._gateway_client = gateway_client

    def set_gateway_client(self, client: Any) -> None:
        """Wire gateway client after initialization."""
        self._gateway_client = client

    @property
    def name(self) -> str:
        return "create_card"

    @property
    def description(self) -> str:
        return (
            "Create a rich card to display structured results to the user. "
            "Cards appear as interactive UI elements in the app."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": {
                "type": "string",
                "required": True,
                "description": (
                    "Card type (e.g., 'flight', 'house', 'pick', 'doc', "
                    "or any custom type)"
                ),
            },
            "title": {
                "type": "string",
                "required": True,
                "description": "Card title",
            },
            "subtitle": {
                "type": "string",
                "required": False,
                "description": "Card subtitle",
            },
            "metadata": {
                "type": "object",
                "required": False,
                "description": (
                    "Fallback key-value metadata for custom card types. "
                    "For typed cards (flight, house, pick, doc), prefer passing "
                    "domain-specific fields as separate top-level parameters instead."
                ),
            },
            "actions": {
                "type": "array",
                "required": False,
                "description": (
                    "Interactive actions. Each has: id (string), "
                    "label (string), type ('link'|'approve'|'dismiss'|"
                    "'copy'|'custom'), url (optional), "
                    "approvalAction (optional)"
                ),
            },
            "ranking": {
                "type": "object",
                "required": False,
                "description": (
                    "Ranking badge with label and reason. "
                    "Labels: 'Best Overall', 'Cheapest', 'Fastest', "
                    "'Best for Points'"
                ),
            },
        }

    async def execute(
        self,
        type: str = "",
        title: str = "",
        subtitle: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        actions: Optional[list[dict[str, Any]]] = None,
        ranking: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Create a card and optionally emit it via the gateway.

        Args:
            type: Card type (flight, house, pick, doc, or custom)
            title: Card title
            subtitle: Optional subtitle
            metadata: Domain-specific fields
            actions: Optional interactive actions
            ranking: Optional ranking badge {label, reason}

        Returns:
            ToolResult with the created card dict as output.
        """
        if not type:
            return self.fail("Missing required parameter: type")
        if not title:
            return self.fail("Missing required parameter: title")

        # Build card matching BaseCard from shared/types/cards.ts
        card: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "type": type,
            "title": title,
            "metadata": metadata or {},
            "source": "agent",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }

        # Add optional fields (strip None values)
        if subtitle is not None:
            card["subtitle"] = subtitle
        if actions is not None:
            card["actions"] = actions
        if ranking is not None:
            card["ranking"] = ranking

        # Merge extra kwargs to root — typed card fields (airline, route, etc.)
        # must be at root level for iOS typed decoders (FlightCard, HouseCard, etc.)
        for key, value in kwargs.items():
            if key not in card:
                card[key] = value

        # For typed cards, also promote metadata keys to root so iOS decoders find them
        _TYPED_CARD_TYPES = {"flight", "house", "pick", "doc"}
        if type in _TYPED_CARD_TYPES and metadata:
            for key, value in metadata.items():
                if key not in card:
                    card[key] = value

        # Card emission handled by agent.py after tool execution — not here.

        logger.info("Created card: type=%s id=%s", type, card["id"])
        return self.success(card)
