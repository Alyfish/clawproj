"""
ClawBot Tool Registry

Base tool class and registry for the agentic loop.

Every tool extends BaseTool and implements:
  - name, description, parameters (declarative metadata)
  - async execute(**kwargs) -> ToolResult (the actual work)

The ToolRegistry holds all registered tools and provides:
  - Tool lookup by name (for dispatching LLM tool_use calls)
  - Tool definitions list (for context_builder.format_tool_descriptions)
  - Execution dispatch with timing, error wrapping, and logging

Design references:
  - OpenManus app/tool/base.py (ABC + execute + ToolResult pattern, __add__, replace)
  - claw0 sessions/en/s02_tool_use.py (dispatch map, truncate(), structured results)
  - learn-claude-code agents/s02_tool_use.py (handler(**block.input) dispatch)
  - server/agent/skill_registry.py (RLock, dict-by-name)
  - Existing ClawBot LOAD_SKILL_TOOL dict shape (compatibility)

Type alignment: shared/types/tools.ts (ToolDefinition, ToolResult, ToolRegistryEntry)
"""
from __future__ import annotations

import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Maximum tool output size before truncation.
# From claw0 sessions/en/s02_tool_use.py: MAX_TOOL_OUTPUT = 50000
MAX_TOOL_OUTPUT = 50_000


def truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    """Truncate text to *limit* chars, appending a note if clipped.

    Ported from claw0 sessions/en/s02_tool_use.py ``truncate()``.
    All tools should use this instead of inline truncation logic.
    """
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text)} total chars]"


# ============================================================
# TOOL RESULT
# ============================================================


@dataclass
class ToolResult:
    """Structured result from a tool execution.

    Fields align with shared/types/tools.ts ToolResult interface.
    tool_call_id and duration_ms are stamped by the ToolRegistry —
    individual tools only need to set success + output/error.

    Every tool returns a ToolResult — callers check fields,
    never catch exceptions.
    """

    success: bool
    output: Any = None
    error: Optional[str] = None
    tool_call_id: str = ""
    duration_ms: Optional[float] = None

    def __bool__(self) -> bool:
        return self.success

    def to_dict(self) -> dict[str, Any]:
        """Serialize to camelCase dict matching shared/types/tools.ts.

        Omits optional fields that are None to keep payloads lean.
        """
        d: dict[str, Any] = {
            "toolCallId": self.tool_call_id,
            "success": self.success,
            "output": self.output,
        }
        if self.error is not None:
            d["error"] = self.error
        if self.duration_ms is not None:
            d["durationMs"] = self.duration_ms
        return d

    def __add__(self, other: "ToolResult") -> "ToolResult":
        """Combine two results by concatenating text fields.

        Ported from OpenManus app/tool/base.py ``ToolResult.__add__``.
        Useful when a tool aggregates results from multiple sub-operations.
        """
        def _combine(a: Any, b: Any) -> Any:
            if a and b:
                if isinstance(a, str) and isinstance(b, str):
                    return a + b
                return a  # non-string: keep first
            return a or b

        return ToolResult(
            success=self.success and other.success,
            output=_combine(self.output, other.output),
            error=_combine(self.error, other.error),
        )

    def replace(self, **kwargs: Any) -> "ToolResult":
        """Return a new ToolResult with the given fields replaced.

        Ported from OpenManus app/tool/base.py ``ToolResult.replace``.
        """
        from dataclasses import asdict
        merged = {**asdict(self), **kwargs}
        return ToolResult(**merged)

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        return str(self.output) if self.output is not None else "(no output)"


# ============================================================
# BASE TOOL
# ============================================================


class BaseTool(ABC):
    """Abstract base class for all ClawBot tools.

    Subclasses must implement:
      - name (property) — tool identifier, e.g. "code_execution"
      - description (property) — one-liner for LLM prompt
      - parameters (property) — JSON Schema dict of parameters
      - execute(**kwargs) — async method that does the work

    Example subclass::

        class MyTool(BaseTool):
            @property
            def name(self) -> str:
                return "my_tool"

            @property
            def description(self) -> str:
                return "Does a thing."

            @property
            def parameters(self) -> dict[str, Any]:
                return {
                    "input": {
                        "type": "string",
                        "required": True,
                        "description": "The input",
                    }
                }

            async def execute(self, **kwargs) -> ToolResult:
                return self.success({"result": kwargs["input"].upper()})
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool identifier (e.g., 'code_execution')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description for the LLM system prompt."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """Parameter definitions as a dict of {name: {type, required, description}}.

        Must match the shape consumed by context_builder.format_tool_descriptions().
        """
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given parameters.

        All keyword arguments come from the LLM's tool_use input dict.
        Must return a ToolResult — never raise exceptions to callers.
        """
        ...

    # --------------------------------------------------------
    # HELPERS
    # --------------------------------------------------------

    def success(self, output: Any = None) -> ToolResult:
        """Create a successful ToolResult."""
        return ToolResult(success=True, output=output)

    def fail(self, error: str) -> ToolResult:
        """Create a failed ToolResult."""
        return ToolResult(success=False, error=error)

    @property
    def requires_approval(self) -> list[str]:
        """Approval actions this tool may trigger.

        Override in tools that need user approval before execution.
        Maps to ToolDefinition.requiresApproval in shared/types/tools.ts.

        Example: ['pay', 'send', 'delete']
        """
        return []

    def get_definition(self) -> dict[str, Any]:
        """Return the Claude API tool_use definition.

        Format: {"name": ..., "description": ..., "input_schema": {...}}
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_tool_definition(self) -> dict[str, Any]:
        """Serialize for context_builder.format_tool_descriptions().

        Format: {"name": ..., "description": ..., "parameters": {...}}
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    async def __call__(self, **kwargs: Any) -> ToolResult:
        """Enable await tool(code="...") syntax."""
        return await self.execute(**kwargs)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


# ============================================================
# TOOL REGISTRY
# ============================================================


class ToolRegistry:
    """Thread-safe registry of tool instances.

    Used by the agentic loop to:
      - Dispatch tool_use calls from the LLM → tool.execute(**input)
      - Provide tool definitions for the system prompt

    Usage::

        registry = ToolRegistry()
        registry.register(CodeExecutionTool())
        registry.register(FileIoTool())

        # Get tool definitions for the system prompt
        defs = registry.get_tool_definitions()
        system_prompt += format_tool_descriptions(defs)

        # Dispatch a tool call
        tool = registry.get("code_execution")
        result = await tool.execute(language="python", code="print(42)")
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._lock = threading.RLock()

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance. Warns on overwrite."""
        with self._lock:
            if tool.name in self._tools:
                logger.warning("Overwriting tool: %s", tool.name)
            self._tools[tool.name] = tool
            logger.info("Registered tool: %s", tool.name)

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if removed."""
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                logger.info("Unregistered tool: %s", name)
                return True
            return False

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name. Returns None if not found."""
        with self._lock:
            return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names (sorted)."""
        with self._lock:
            return sorted(self._tools.keys())

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions for context_builder.format_tool_descriptions().

        Returns a list of dicts, each with {name, description, parameters}.
        """
        with self._lock:
            return [
                tool.to_tool_definition()
                for tool in sorted(self._tools.values(), key=lambda t: t.name)
            ]

    @property
    def count(self) -> int:
        """Number of registered tools."""
        with self._lock:
            return len(self._tools)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._tools

    async def execute(
        self,
        tool_name: str,
        tool_call_id: str,
        params: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Dispatch a tool call with timing, error wrapping, and logging.

        Args:
            tool_name: Registered tool name (e.g., "web_search")
            tool_call_id: Correlation ID from Claude's tool_use block
            params: Parameters from Claude's tool_use input dict

        Returns:
            ToolResult — always, never raises.
        """
        if params is None:
            params = {}

        with self._lock:
            tool = self._tools.get(tool_name)

        if tool is None:
            available = self.list_tools()
            return ToolResult(
                success=False,
                tool_call_id=tool_call_id,
                error=(
                    f"Unknown tool '{tool_name}'. "
                    f"Available: {', '.join(available) or '(none)'}"
                ),
            )

        t0 = time.monotonic()
        try:
            result = await tool.execute(**params)
        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.error(
                "tool=%s call_id=%s duration=%.1fms error=%s: %s",
                tool_name, tool_call_id, elapsed_ms, type(e).__name__, e,
            )
            return ToolResult(
                success=False,
                tool_call_id=tool_call_id,
                error=f"{type(e).__name__}: {e}",
                duration_ms=round(elapsed_ms, 1),
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        result.tool_call_id = tool_call_id
        result.duration_ms = round(elapsed_ms, 1)

        logger.info(
            "tool=%s call_id=%s duration=%.1fms success=%s",
            tool_name, tool_call_id, elapsed_ms, result.success,
        )
        return result

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={self.list_tools()}>"


# ============================================================
# CREDENTIAL STORE (placeholder until CredentialStore is wired)
# ============================================================


def get_credential(name: str) -> dict[str, str] | None:
    """Get credential by name. Checks env var CLAWBOT_CRED_{NAME}.

    Returns:
        {"type": "api_key", "value": "<value>"} or None if not found.
    """
    env_key = f"CLAWBOT_CRED_{name.upper()}"
    value = os.environ.get(env_key)
    if value:
        return {"type": "api_key", "value": value}
    return None
