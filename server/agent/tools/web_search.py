"""
ClawBot Web Search Tool

Searches the web for current information using SerpAPI.
Supports mock mode for development (set CLAWBOT_MOCK_SEARCH=1).

Design references:
  - OpenManus app/tool/web_search.py (API key validation, result normalization)
  - claw0 sessions/en/s02_tool_use.py (output truncation, error wrapping)
  - learn-claude-code agents/s02_tool_use.py (handler dispatch pattern)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Optional

import httpx

from server.agent.tools.tool_registry import BaseTool, ToolResult, get_credential

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search"
DEFAULT_NUM_RESULTS = 5
MAX_NUM_RESULTS = 10
SEARCH_TIMEOUT = 15  # seconds


class WebSearchTool(BaseTool):
    """Search the web for current information.

    Uses SerpAPI for real searches. Set CLAWBOT_MOCK_SEARCH=1
    for development without an API key.
    """

    def __init__(
        self, credential_store: Optional[Callable[[str], dict | None]] = None
    ) -> None:
        self._credential_store = credential_store or get_credential

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for current information. Use when you need "
            "recent data, news, or information not in your training data."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "required": True,
                "description": "Search query",
            },
            "num_results": {
                "type": "integer",
                "required": False,
                "description": "Number of results to return (1-10, default 5)",
            },
        }

    async def execute(
        self,
        query: str = "",
        num_results: int = DEFAULT_NUM_RESULTS,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a web search.

        Args:
            query: Search query string
            num_results: Number of results (1-10, default 5)

        Returns:
            ToolResult with output: list of {title, url, snippet}
        """
        query = query.strip()
        num_results = max(1, min(int(num_results), MAX_NUM_RESULTS))

        if not query:
            return self.fail("Missing required parameter: query")

        # Mock mode for development (OpenManus pattern: check before API call)
        if os.environ.get("CLAWBOT_MOCK_SEARCH") == "1":
            logger.info("Web search (mock): %s", query)
            return self.success(self._mock_results(query, num_results))

        # Look up SerpAPI credential
        cred = self._credential_store("serpapi")
        if cred is None:
            return self.fail(
                "Web search not configured. "
                "Set CLAWBOT_CRED_SERPAPI environment variable."
            )

        api_key = cred.get("value", "")

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
                response = await client.get(
                    SERPAPI_URL,
                    params={
                        "q": query,
                        "api_key": api_key,
                        "num": num_results,
                    },
                )
                response.raise_for_status()

            elapsed_ms = (time.monotonic() - start) * 1000
            logger.info(
                "Web search: '%s' -> %d (%.0fms)",
                query, response.status_code, elapsed_ms,
            )

            data = response.json()
            organic = data.get("organic_results", [])

            results = [
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
                for item in organic[:num_results]
            ]

            return self.success(results)

        except httpx.TimeoutException:
            logger.warning("Web search timed out: '%s'", query)
            return self.fail("Search timed out")

        except httpx.HTTPStatusError as e:
            logger.warning("Web search API error: %d", e.response.status_code)
            return self.fail(f"Search API error: {e.response.status_code}")

        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Web search parse error: %s", e)
            return self.fail("Failed to parse search results")

        except Exception as e:
            logger.warning("Web search failed: %s", e)
            return self.fail(f"Web search failed: {type(e).__name__}: {e}")

    @staticmethod
    def _mock_results(query: str, num: int) -> list[dict[str, str]]:
        """Generate mock search results for development."""
        return [
            {
                "title": f"Result {i + 1} for: {query}",
                "url": f"https://example.com/{i + 1}",
                "snippet": f"This is mock search result {i + 1} for '{query}'.",
            }
            for i in range(num)
        ]
