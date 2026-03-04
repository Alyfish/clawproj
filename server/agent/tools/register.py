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
from server.agent.tools.browser_cdp import CDPBrowserTool
from server.agent.tools.profile_manager import ProfileManagerTool
from server.agent.tools.vision import VisionTool
from server.agent.browser_profiles import BrowserProfileManager
from server.agent.tools.login_flow import LoginFlowManager
from server.agent.tools.schedule import ScheduleTool


def create_registry(
    gateway_client: Optional[Any] = None,
    memory_system: Optional[Any] = None,
    credential_store: Optional[Callable[[str], dict | None]] = None,
) -> tuple[ToolRegistry, LoginFlowManager | None]:
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

    # Browser automation with profile support
    try:
        profile_manager = BrowserProfileManager()
    except OSError:
        profile_manager = None
        import logging
        logging.getLogger(__name__).warning(
            "Browser profiles unavailable (could not create profile dir). "
            "Set BROWSER_PROFILES_DIR to a writable path."
        )

    browser_tool = CDPBrowserTool(profile_manager=profile_manager)
    registry.register(browser_tool)
    if profile_manager is not None:
        registry.register(ProfileManagerTool(profile_manager=profile_manager))

    # Login flow manager (delegates to browser + profiles + gateway)
    login_flow_manager = LoginFlowManager(
        browser_tool=browser_tool,
        gateway_client=gateway_client,
        profile_manager=profile_manager,
    )
    browser_tool.set_login_flow_manager(login_flow_manager)

    # Vision extraction (agentic multi-pass pipeline)
    registry.register(VisionTool())

    # Schedule tool (manages watches via gateway scheduler)
    schedule_tool = ScheduleTool(gateway_client=gateway_client)
    registry.register(schedule_tool)

    return registry, login_flow_manager
