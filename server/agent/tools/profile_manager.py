"""
ClawBot Browser Profile Manager Tool

Manage persistent browser profiles for login session persistence.
Wraps BrowserProfileManager for LLM-callable profile management.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from server.agent.tools.tool_registry import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class ProfileManagerTool(BaseTool):
    """Manage persistent browser profiles for login sessions."""

    def __init__(self, profile_manager: Optional[Any] = None) -> None:
        self._profile_manager = profile_manager

    @property
    def name(self) -> str:
        return "browser_profiles"

    @property
    def description(self) -> str:
        return (
            "Manage persistent browser profiles for login sessions. "
            "Create named profiles to keep different accounts separate. "
            "Login sessions (cookies, localStorage) persist across browser restarts. "
            "Use the 'profile' parameter on the browser tool to browse with a specific profile."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "description": "Profile action to perform",
                "enum": ["list", "create", "delete", "show_domains"],
            },
            "name": {
                "type": "string",
                "required": False,
                "description": "Profile name (required for create, delete, show_domains)",
            },
            "notes": {
                "type": "string",
                "required": False,
                "description": "Optional notes when creating a profile",
            },
        }

    async def execute(
        self,
        action: str = "",
        name: str = "",
        notes: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if self._profile_manager is None:
            return self.fail("Browser profile manager not configured.")
        if not action:
            return self.fail("Missing required parameter: action")

        if action == "list":
            profiles = self._profile_manager.list_profiles()
            result = [p.to_dict() for p in profiles]
            return self.success(json.dumps(result, indent=2))

        elif action == "create":
            if not name:
                return self.fail("Missing required parameter: name")
            try:
                profile = self._profile_manager.create_profile(name, notes=notes)
                return self.success(json.dumps(profile.to_dict(), indent=2))
            except ValueError as e:
                return self.fail(str(e))

        elif action == "delete":
            if not name:
                return self.fail("Missing required parameter: name")
            deleted = self._profile_manager.delete_profile(name)
            if deleted:
                return self.success(json.dumps({"deleted": True, "name": name}))
            return self.fail(f"Profile '{name}' not found or cannot be deleted.")

        elif action == "show_domains":
            if not name:
                return self.fail("Missing required parameter: name")
            profile = self._profile_manager.get_profile(name)
            if profile is None:
                return self.fail(f"Profile '{name}' not found.")
            return self.success(json.dumps({
                "profile": name,
                "authenticated_domains": profile.authenticated_domains,
            }, indent=2))

        else:
            return self.fail(
                f"Unknown action '{action}'. "
                f"Available: list, create, delete, show_domains"
            )
