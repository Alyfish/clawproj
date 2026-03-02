"""
ClawBot HTTP Request Tool

Makes HTTP requests to external APIs. Used by skills that need to call
third-party services (flights, apartments, search engines, etc.).

Security:
  - NEVER logs request body or auth headers
  - Redacts query params from logs (may contain API keys)
  - Truncates response body at 50KB to prevent context blowout

Design references:
  - OpenManus app/tool/base.py (success/fail helpers, structured ToolResult)
  - claw0 sessions/en/s02_tool_use.py (truncate() at 50K, timeout enforcement)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx

from server.agent.tools.tool_registry import BaseTool, ToolResult, get_credential, truncate

logger = logging.getLogger(__name__)

# Absolute max timeout to prevent abuse
MAX_TIMEOUT_SECONDS = 120


class HttpRequestTool(BaseTool):
    """Make HTTP requests to any API endpoint.

    The LLM calls this tool when a skill needs to interact with
    external APIs (flights, apartments, search engines, etc.).
    Credential injection is supported for authenticated APIs.
    """

    def __init__(
        self, credential_store: Optional[Callable[[str], dict | None]] = None
    ) -> None:
        self._credential_store = credential_store or get_credential

    @property
    def name(self) -> str:
        return "http_request"

    @property
    def description(self) -> str:
        return (
            "Make HTTP requests to any API. Use this to call external APIs "
            "described in skill instructions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "method": {
                "type": "string",
                "required": True,
                "description": "HTTP method",
                "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
            },
            "url": {
                "type": "string",
                "required": True,
                "description": "Request URL",
            },
            "headers": {
                "type": "object",
                "required": False,
                "description": "Request headers",
            },
            "body": {
                "type": "object",
                "required": False,
                "description": "Request body (for POST/PUT/PATCH)",
            },
            "query_params": {
                "type": "object",
                "required": False,
                "description": "URL query parameters",
            },
            "credential": {
                "type": "string",
                "required": False,
                "description": "Credential name from credential store",
            },
            "timeout": {
                "type": "number",
                "required": False,
                "description": "Request timeout in seconds (default 30, max 120)",
            },
        }

    async def execute(
        self,
        method: str = "GET",
        url: str = "",
        headers: Optional[dict[str, str]] = None,
        body: Any = None,
        query_params: Optional[dict[str, str]] = None,
        credential: Optional[str] = None,
        timeout: float = 30,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute an HTTP request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            url: Target URL
            headers: Optional request headers
            body: Optional request body (JSON for POST/PUT/PATCH)
            query_params: Optional URL query parameters
            credential: Optional credential name for auth injection
            timeout: Request timeout in seconds (max 120)

        Returns:
            ToolResult with output: {status_code, headers, body, elapsed_ms}
        """
        method = method.upper()
        headers = dict(headers or {})
        timeout_s = min(float(timeout or 30), MAX_TIMEOUT_SECONDS)

        if not url:
            return self.fail("Missing required parameter: url")

        # Resolve credential
        if credential:
            cred = self._credential_store(credential)
            if cred is None:
                return self.fail(
                    f"Credential '{credential}' not found. "
                    f"Set CLAWBOT_CRED_{credential.upper()} environment variable."
                )
            cred_type = cred.get("type", "api_key")
            cred_value = cred.get("value", "")
            if cred_type == "api_key":
                headers.setdefault("Authorization", f"Bearer {cred_value}")
            elif cred_type == "header":
                if ":" in cred_value:
                    h_name, h_val = cred_value.split(":", 1)
                    headers[h_name.strip()] = h_val.strip()

        # Security: log only safe info (host, method — no body/headers/params)
        parsed = urlparse(url)
        log_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body if body is not None and method in ("POST", "PUT", "PATCH") else None,
                    params=query_params,
                )

            elapsed_ms = (time.monotonic() - start) * 1000

            logger.info(
                "HTTP %s %s -> %d (%.0fms)", method, log_url,
                response.status_code, elapsed_ms,
            )

            # Parse response body
            try:
                response_body: Any = response.json()
            except (ValueError, TypeError):
                response_body = response.text

            # Truncate large responses (shared truncate from claw0)
            if isinstance(response_body, str):
                response_body = truncate(response_body)

            # Extract safe response headers only
            resp_headers = {}
            for h in ("content-type", "x-request-id"):
                val = response.headers.get(h)
                if val:
                    resp_headers[h] = val

            return self.success({
                "status_code": response.status_code,
                "headers": resp_headers,
                "body": response_body,
                "elapsed_ms": round(elapsed_ms, 1),
            })

        except httpx.TimeoutException:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("HTTP %s %s timed out after %.0fms", method, log_url, elapsed_ms)
            return self.fail(f"Request timed out after {timeout_s}s")

        except httpx.ConnectError:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("HTTP %s %s connection failed", method, log_url)
            return self.fail(f"Connection failed: {url}")

        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("HTTP %s %s failed: %s", method, log_url, e)
            return self.fail(f"HTTP request failed: {type(e).__name__}: {e}")
