"""
Register all base tools with the ToolRegistry.

Call create_registry() at server startup to get a fully populated
ToolRegistry with all 8 base tools.

Usage:
    from server.agent.tools.register import create_registry
    registry = create_registry(
        gateway_client=my_gateway,
        memory_system=my_memory,
    )
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from server.agent.tools.tool_registry import ToolRegistry
from server.agent.tools.code_execution import CodeExecutionTool
from server.agent.tools.file_io import FileIoTool
from server.agent.tools.http_request import HttpRequestTool
from server.agent.tools.web_search import WebSearchTool
from server.agent.tools.create_card import CreateCardTool
from server.agent.tools.memory_tools import SaveMemoryTool, SearchMemoryTool
from server.agent.tools.request_approval import RequestApprovalTool
from server.agent.tools.browser_bridge import BrowserBridge
from server.agent.tools.vision import VisionTool


def create_registry(
    gateway_client: Optional[Any] = None,
    memory_system: Optional[Any] = None,
    credential_store: Optional[Callable[[str], dict | None]] = None,
) -> ToolRegistry:
    """Create a ToolRegistry with all base tools registered.

    Args:
        gateway_client: Gateway client for card/approval tools.
            Must implement emit_event() and request_approval().
        memory_system: Memory backend for save/search memory tools.
            Must implement save() and search().
        credential_store: Callable(name) -> {type, value} or None.
            Used by HTTP and web search tools for API key injection.
            Falls back to env-var lookup (CLAWBOT_CRED_{NAME}) if None.

    Returns:
        ToolRegistry with all tools ready for dispatch.
    """
    registry = ToolRegistry()

    # Tools with no external dependencies
    registry.register(CodeExecutionTool())
    registry.register(FileIoTool())

    # Tools that use credential store
    registry.register(HttpRequestTool(credential_store=credential_store))
    registry.register(WebSearchTool(credential_store=credential_store))

    # Tools that use gateway client
    registry.register(CreateCardTool(gateway_client=gateway_client))
    registry.register(RequestApprovalTool(gateway_client=gateway_client))

    # Tools that use memory system
    registry.register(SaveMemoryTool(memory_system=memory_system))
    registry.register(SearchMemoryTool(memory_system=memory_system))

    # Browser automation (manages its own Node.js sidecar)
    registry.register(BrowserBridge())

    # Vision extraction (agentic multi-pass pipeline)
    registry.register(VisionTool())

    return registry
