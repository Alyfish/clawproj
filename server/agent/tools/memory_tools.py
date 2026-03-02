"""
ClawBot Memory Tools

Save and search agent memory for cross-conversation context.
Two tool classes: SaveMemoryTool and SearchMemoryTool.

Design references:
  - OpenManus Terminate (minimal tool, delegates to system)
  - claw0 s02_tools (structured {status, results} responses)
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from server.agent.tools.tool_registry import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class MemorySystem(Protocol):
    """Memory system interface (Chunk 16, not yet built)."""

    async def save(
        self, key: str, content: str, tags: list[str] | None = None
    ) -> None: ...

    async def search(
        self, query: str, limit: int = 5
    ) -> list[dict]: ...


# ============================================================
# SAVE MEMORY
# ============================================================


class SaveMemoryTool(BaseTool):
    """Save information for future conversations.

    Use to remember user preferences, past searches, or important
    context that should persist across conversations.
    """

    def __init__(
        self, memory_system: Optional[Any] = None
    ) -> None:
        self._memory_system = memory_system

    @property
    def name(self) -> str:
        return "save_memory"

    @property
    def description(self) -> str:
        return (
            "Save information for future conversations. Use to remember "
            "user preferences, past searches, or important context."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "key": {
                "type": "string",
                "required": True,
                "description": "Unique key for this memory entry",
            },
            "content": {
                "type": "string",
                "required": True,
                "description": "The information to save",
            },
            "tags": {
                "type": "array",
                "required": False,
                "description": "Optional tags for categorization and search",
                "items": {"type": "string"},
            },
        }

    async def execute(
        self,
        key: str = "",
        content: str = "",
        tags: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Save a memory entry.

        Args:
            key: Unique key for the entry
            content: Information to save
            tags: Optional categorization tags

        Returns:
            ToolResult confirming save, or error if not configured.
        """
        if self._memory_system is None:
            return self.fail(
                "Memory system not configured. "
                "Memory features are not available yet."
            )

        if not key:
            return self.fail("Missing required parameter: key")
        if not content:
            return self.fail("Missing required parameter: content")

        try:
            await self._memory_system.save(key, content, tags)
        except Exception as e:
            logger.warning("Memory save failed: key=%s error=%s", key, e)
            return self.fail(f"Failed to save memory: {e}")

        logger.info("Saved memory: key=%s size=%d", key, len(content))
        return self.success({"saved": True, "key": key})


# ============================================================
# SEARCH MEMORY
# ============================================================


class SearchMemoryTool(BaseTool):
    """Search saved memories for relevant context.

    Returns matching entries ranked by relevance.
    """

    def __init__(
        self, memory_system: Optional[Any] = None
    ) -> None:
        self._memory_system = memory_system

    @property
    def name(self) -> str:
        return "search_memory"

    @property
    def description(self) -> str:
        return "Search saved memories for relevant context."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "required": True,
                "description": "Search query",
            },
            "top_k": {
                "type": "integer",
                "required": False,
                "description": "Number of results to return (default 5)",
            },
        }

    async def execute(
        self,
        query: str = "",
        top_k: int = 5,
        **kwargs: Any,
    ) -> ToolResult:
        """Search memories by query.

        Args:
            query: Search query string
            top_k: Number of results (default 5)

        Returns:
            ToolResult with list of matching entries, or error if
            not configured.
        """
        if self._memory_system is None:
            return self.fail("Memory system not configured.")

        if not query:
            return self.fail("Missing required parameter: query")

        try:
            results = await self._memory_system.search(
                query, limit=max(1, int(top_k))
            )
        except Exception as e:
            logger.warning("Memory search failed: query=%s error=%s", query, e)
            return self.fail(f"Failed to search memory: {e}")

        logger.info(
            "Memory search: query=%s results=%d", query, len(results)
        )
        return self.success(results)
