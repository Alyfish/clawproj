"""
ClawBot Agent Tools

Base tool infrastructure and concrete tool implementations
for the agentic loop.
"""

from server.agent.tools.tool_registry import BaseTool, ToolRegistry, ToolResult, get_credential, truncate
from server.agent.tools.code_execution import CodeExecutionTool
from server.agent.tools.file_io import FileIoTool
from server.agent.tools.http_request import HttpRequestTool
from server.agent.tools.web_search import WebSearchTool
from server.agent.tools.create_card import CreateCardTool
from server.agent.tools.memory_tools import SaveMemoryTool, SearchMemoryTool
from server.agent.tools.request_approval import RequestApprovalTool
from server.agent.tools.browser_bridge import BrowserBridge
from server.agent.tools.vision import VisionTool
from server.agent.tools.register import create_registry


def create_default_registry(**kwargs) -> ToolRegistry:
    """Create a ToolRegistry with all built-in tools registered.

    Args:
        gateway_client: Optional gateway client for card/approval tools.
        memory_system: Optional memory system for memory tools.
    """
    registry = ToolRegistry()
    registry.register(CodeExecutionTool())
    registry.register(FileIoTool())
    registry.register(HttpRequestTool())
    registry.register(WebSearchTool())
    registry.register(CreateCardTool(gateway_client=kwargs.get("gateway_client")))
    registry.register(SaveMemoryTool(memory_system=kwargs.get("memory_system")))
    registry.register(SearchMemoryTool(memory_system=kwargs.get("memory_system")))
    registry.register(RequestApprovalTool(gateway_client=kwargs.get("gateway_client")))
    registry.register(BrowserBridge())
    registry.register(VisionTool())
    return registry


__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolRegistry",
    "get_credential",
    "truncate",
    "CodeExecutionTool",
    "FileIoTool",
    "HttpRequestTool",
    "WebSearchTool",
    "CreateCardTool",
    "SaveMemoryTool",
    "SearchMemoryTool",
    "RequestApprovalTool",
    "BrowserBridge",
    "VisionTool",
    "create_default_registry",
    "create_registry",
]
