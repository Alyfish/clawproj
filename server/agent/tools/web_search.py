"""
ClawBot Web Search Tool

Searches the web using a provider cascade:
  1. Mock mode (CLAWBOT_MOCK_SEARCH=1)
  2. SerpAPI (if CLAWBOT_CRED_SERPAPI credential exists)
  3. SearXNG (zero-config fallback, default http://searxng:8080)

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
SEARXNG_TIMEOUT = 10  # seconds
DEFAULT_SEARXNG_URL = "http://searxng:8080"


class WebSearchTool(BaseTool):
    """Search the web for current information.

    Provider cascade:
      1. Mock mode (CLAWBOT_MOCK_SEARCH=1)
      2. SerpAPI (needs CLAWBOT_CRED_SERPAPI)
      3. SearXNG (zero-config fallback)
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

        # --- Provider cascade ---

        # 1. Try SerpAPI if credential exists
        cred = self._credential_store("serpapi")
        if cred is not None:
            try:
                return await self._search_serpapi(query, num_results, cred)
            except Exception as e:
                logger.warning(
                    "SerpAPI failed, falling through to SearXNG: %s", e
                )

        # 2. Try SearXNG (zero-config fallback)
        try:
            results = await self._search_searxng(query, num_results)
            return self.success(results)
        except httpx.TimeoutException:
            logger.warning("SearXNG search timed out: '%s'", query)
            return self.fail("Search timed out (SearXNG)")
        except httpx.ConnectError:
            logger.warning("SearXNG not reachable")
            return self.fail(
                "Search unavailable. Is the searxng container running?"
            )
        except Exception as e:
            logger.warning("SearXNG search failed: %s", e)
            return self.fail(
                "Search unavailable. Is the searxng container running?"
            )

    # ------------------------------------------------------------------
    # PROVIDERS
    # ------------------------------------------------------------------

    async def _search_serpapi(
        self,
        query: str,
        num_results: int,
        cred: dict[str, str],
    ) -> ToolResult:
        """Search via SerpAPI. Raises on failure (caller falls through)."""
        api_key = cred.get("value", "")

        start = time.monotonic()
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
            "Web search (SerpAPI): '%s' -> %d (%.0fms)",
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

    async def _search_searxng(
        self, query: str, num_results: int
    ) -> list[dict[str, str]]:
        """Search via SearXNG. Returns list of {title, url, snippet}.

        Raises on failure (caller handles exceptions).
        """
        searxng_url = os.environ.get(
            "CLAWBOT_SEARXNG_URL", DEFAULT_SEARXNG_URL
        )

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=SEARXNG_TIMEOUT) as client:
            response = await client.get(
                f"{searxng_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "categories": "general",
                    "language": "en",
                },
            )
            response.raise_for_status()

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "Web search (SearXNG): '%s' -> %d (%.0fms)",
            query, response.status_code, elapsed_ms,
        )

        data = response.json()
        items = data.get("results", [])

        # Sort by score descending (SearXNG provides relevance scores)
        items.sort(key=lambda x: x.get("score", 0), reverse=True)

        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", ""),
            }
            for item in items[:num_results]
        ]

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
