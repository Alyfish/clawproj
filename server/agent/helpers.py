"""
ClawBot Agent Helpers

Shared utility functions for the agentic loop. Used by agent.py,
gateway_client.py, and main.py.

Functions:
  - generate_run_id / generate_session_id — unique identifiers
  - describe_tool_call — human-readable tool call descriptions for thinking steps
  - summarize_result — short summaries of tool results
  - truncate_for_context — text truncation with note
  - Timer — context manager for timing operations
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def generate_run_id() -> str:
    """Generate a unique run ID for a single agent turn."""
    return f"run_{uuid.uuid4().hex[:12]}"


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return f"sess_{uuid.uuid4().hex[:16]}"


def describe_tool_call(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Create a human-readable description of a tool call for thinking steps.

    Examples:
      describe_tool_call("http_request", {"method": "GET", "url": "https://..."})
      → "HTTP GET https://..."

      describe_tool_call("web_search", {"query": "cheap flights SFO to London"})
      → "Searching: cheap flights SFO to London"

      describe_tool_call("code_execution", {"language": "python", "code": "..."})
      → "Running Python code (23 lines)"

      describe_tool_call("create_card", {"type": "flight", "title": "..."})
      → "Creating flight card: ..."
    """
    try:
        if tool_name == "http_request":
            method = tool_input.get("method", "GET").upper()
            url = tool_input.get("url", "unknown")
            if len(url) > 80:
                url = url[:77] + "..."
            return f"HTTP {method} {url}"

        elif tool_name == "web_search":
            query = tool_input.get("query", "")
            return f"Searching: {query}"

        elif tool_name == "code_execution":
            lang = tool_input.get("language", "python")
            code = tool_input.get("code", "")
            line_count = code.count("\n") + 1
            return f"Running {lang} code ({line_count} lines)"

        elif tool_name == "file_io":
            action = tool_input.get("action", "read")
            path = tool_input.get("path", "unknown")
            return f"File {action}: {path}"

        elif tool_name == "create_card":
            card_type = tool_input.get("type", "unknown")
            title = tool_input.get("title", "untitled")
            if len(title) > 50:
                title = title[:47] + "..."
            return f"Creating {card_type} card: {title}"

        elif tool_name == "save_memory":
            key = tool_input.get("key", "unknown")
            return f"Saving to memory: {key}"

        elif tool_name == "search_memory":
            query = tool_input.get("query", "")
            return f"Searching memory: {query}"

        elif tool_name == "request_approval":
            action = tool_input.get("action", "unknown")
            desc = tool_input.get("description", "")
            if len(desc) > 60:
                desc = desc[:57] + "..."
            return f"Requesting approval ({action}): {desc}"

        elif tool_name == "load_skill":
            skill_name = tool_input.get("skill_name", "unknown")
            return f"Loading skill: {skill_name}"

        elif tool_name == "browser":
            action = tool_input.get("action", "unknown")
            params = tool_input.get("params", {})
            if action == "navigate":
                return f"Navigating to: {params.get('url', 'unknown')}"
            elif action == "search":
                return f"Searching {params.get('site', 'web')}: {params.get('query', '')}"
            elif action == "click":
                return f"Clicking: {params.get('selector_or_text', 'element')}"
            elif action == "fill_form":
                field_count = len(params.get("fields", []))
                return f"Filling {field_count} form fields"
            else:
                return f"Browser: {action}"

        else:
            # Generic fallback
            summary_parts = []
            for key, val in list(tool_input.items())[:3]:
                val_str = str(val)
                if len(val_str) > 40:
                    val_str = val_str[:37] + "..."
                summary_parts.append(f"{key}={val_str}")
            params_str = ", ".join(summary_parts) if summary_parts else "no params"
            return f"{tool_name}({params_str})"

    except Exception:
        return f"{tool_name}(\u2026)"


def summarize_result(result: Any, max_length: int = 200) -> str:
    """Create a short summary of a tool result for thinking step display."""
    try:
        if hasattr(result, "success") and hasattr(result, "output"):
            # ToolResult-like object
            if not result.success:
                error_msg = result.error or "Unknown error"
                return f"\u274c {error_msg[:max_length - 2]}"
            text = (
                result.output
                if isinstance(result.output, str)
                else json.dumps(result.output, default=str)
            )
        elif isinstance(result, dict):
            text = json.dumps(result, default=str)
        elif isinstance(result, str):
            text = result
        else:
            text = str(result)

        if len(text) > max_length:
            return text[: max_length - 3] + "..."
        return text
    except Exception:
        return "Result (could not summarize)"


def truncate_for_context(text: str, max_chars: int = 50_000) -> str:
    """Truncate text to fit within context limits, with a note."""
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars]
        + f"\n... [truncated \u2014 {len(text)} chars total, showing first {max_chars}]"
    )


class Timer:
    """Simple context manager for timing operations."""

    def __init__(self) -> None:
        self.start_time: float = 0
        self.duration_ms: float = 0

    def __enter__(self) -> Timer:
        self.start_time = time.time()
        return self

    def __exit__(self, *args: object) -> None:
        self.duration_ms = (time.time() - self.start_time) * 1000
