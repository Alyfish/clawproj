"""
Comprehensive tests for LoginFlowManager.

Tests all methods:
- start_login_flow (success, invalid profile, navigation failure, cancellation)
- send_login_input (success, no active flow, stale ref)
- click_login_element (success, no active flow, stale ref)
- stop_login_flow (authenticated, unauthenticated, task cancellation)
- shutdown (clears all flows)
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.agent.tools.browser_js import DOM_WALKER_JS, JS_LOOKUP_REF, JS_CHECK_AUTH_INDICATORS
from server.agent.tools.login_flow import LoginFlowManager
from server.agent.tools.tool_registry import ToolResult


@dataclass
class MockPage:
    """Mock Playwright page with required methods."""
    url: str = "https://example.com/login"
    _title: str = "Login Page"
    _closed: bool = False

    def is_closed(self) -> bool:
        return self._closed

    async def title(self) -> str:
        return self._title

    async def screenshot(self, type: str = "jpeg", quality: int = 60) -> bytes:
        return b"fake_jpeg_data"

    def __post_init__(self):
        self._locators = {}  # selector -> locator mock (stable across calls)
        self._auth_result = False  # what JS_CHECK_AUTH_INDICATORS returns

    async def evaluate(self, script: str, *args):
        if script is DOM_WALKER_JS or "buildSnapshot" in script:
            return {
                "snapshot": "[1] input Email\n[2] button Login",
                "elementCount": 2,
            }
        if "Object.entries" in script and "__clawbot_refs" in script:
            return [
                {
                    "ref": 1,
                    "tag": "input",
                    "type": None,
                    "text": "input Email",
                    "rect": {"x": 10, "y": 20, "width": 200, "height": 30},
                },
                {
                    "ref": 2,
                    "tag": "button",
                    "type": None,
                    "text": "button Login",
                    "rect": {"x": 10, "y": 60, "width": 100, "height": 40},
                },
            ]
        if script is JS_LOOKUP_REF or ("__clawbot_refs" in script and "String(ref)" in script):
            ref = args[0] if args else None
            if ref == 1:
                return {
                    "selector": "#email",
                    "tagName": "input",
                    "description": "input Email",
                    "rect": {"x": 10, "y": 20, "width": 200, "height": 30},
                }
            if ref == 2:
                return {
                    "selector": "#login-btn",
                    "tagName": "button",
                    "description": "button Login",
                    "rect": {"x": 10, "y": 60, "width": 100, "height": 40},
                }
            return None
        if script is JS_CHECK_AUTH_INDICATORS or "logout" in script:
            return self._auth_result
        return None

    def locator(self, selector: str):
        """Return a stable locator mock for a given selector."""
        if selector not in self._locators:
            locator = MagicMock()
            first = MagicMock()
            first.scroll_into_view_if_needed = AsyncMock()
            first.fill = AsyncMock()
            first.type = AsyncMock()
            first.click = AsyncMock()
            locator.first = first
            self._locators[selector] = locator
        return self._locators[selector]

    async def wait_for_load_state(self, state: str, timeout: int):
        await asyncio.sleep(0)


@pytest.fixture
def mock_browser():
    browser = MagicMock()
    browser._pages = {}
    browser.execute = AsyncMock()
    return browser


@pytest.fixture
def mock_gateway():
    gateway = MagicMock()
    gateway.emit_event = AsyncMock()
    return gateway


@pytest.fixture
def mock_profile_manager():
    manager = MagicMock()
    manager.get_profile = MagicMock(return_value={"name": "test-profile"})
    manager.get_or_create_default = MagicMock()
    manager.add_authenticated_domain = MagicMock()
    return manager


@pytest.fixture
def login_manager(mock_browser, mock_gateway, mock_profile_manager):
    return LoginFlowManager(mock_browser, mock_gateway, mock_profile_manager)


@pytest.mark.asyncio
async def test_start_flow_success(login_manager, mock_browser, mock_profile_manager):
    mock_browser.execute.return_value = ToolResult(
        success=True,
        output="Navigated to https://example.com/login",
        error=None,
    )

    result = await login_manager.start_login_flow(
        profile="test-profile",
        url="https://example.com/login",
        interval_ms=1000,
    )

    assert result["success"] is True
    assert result["profile"] == "test-profile"
    assert result["url"] == "https://example.com/login"

    mock_profile_manager.get_profile.assert_called_once_with("test-profile")
    mock_browser.execute.assert_called_once_with(
        action="navigate",
        params={"url": "https://example.com/login"},
        session_id="login-test-profile",
        profile="test-profile",
    )

    assert "test-profile" in login_manager._active_flows
    assert login_manager._flow_sessions["test-profile"] == "login-test-profile"

    task = login_manager._active_flows["test-profile"]
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_start_flow_default_profile(login_manager, mock_browser, mock_profile_manager):
    mock_browser.execute.return_value = ToolResult(
        success=True,
        output="Navigated",
        error=None,
    )

    result = await login_manager.start_login_flow(
        profile="default",
        url="https://example.com/login",
    )

    assert result["success"] is True
    mock_profile_manager.get_or_create_default.assert_called_once()

    task = login_manager._active_flows.get("default")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_start_flow_invalid_profile(login_manager, mock_profile_manager):
    mock_profile_manager.get_profile.return_value = None

    result = await login_manager.start_login_flow(
        profile="nonexistent",
        url="https://example.com/login",
    )

    assert result["success"] is False
    assert "Profile 'nonexistent' not found" in result["error"]
    assert "nonexistent" not in login_manager._active_flows


@pytest.mark.asyncio
async def test_start_flow_navigate_failure(login_manager, mock_browser, mock_profile_manager):
    mock_browser.execute.return_value = ToolResult(
        success=False,
        output="",
        error="Navigation timeout",
    )

    result = await login_manager.start_login_flow(
        profile="test-profile",
        url="https://example.com/login",
    )

    assert result["success"] is False
    assert "Navigation failed" in result["error"]
    assert "timeout" in result["error"]
    assert "test-profile" not in login_manager._active_flows


@pytest.mark.asyncio
async def test_cancel_existing_flow(login_manager, mock_browser, mock_profile_manager):
    mock_browser.execute.return_value = ToolResult(success=True, output="", error=None)

    first_result = await login_manager.start_login_flow(
        profile="test-profile",
        url="https://first.com",
    )
    assert first_result["success"] is True
    first_task = login_manager._active_flows["test-profile"]

    await asyncio.sleep(0.01)

    second_result = await login_manager.start_login_flow(
        profile="test-profile",
        url="https://second.com",
    )
    assert second_result["success"] is True

    # First task should be done (cancelled or finished cleanly)
    assert first_task.done()

    second_task = login_manager._active_flows["test-profile"]
    second_task.cancel()
    try:
        await second_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_screenshot_loop_streams_frames(login_manager, mock_gateway):
    mock_page = MockPage()
    session_id = "login-test"
    login_manager._browser._pages[session_id] = mock_page

    task = asyncio.create_task(
        login_manager._screenshot_loop("test", session_id, interval_ms=100)
    )

    await asyncio.sleep(0.25)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert mock_gateway.emit_event.call_count >= 1
    call_args = mock_gateway.emit_event.call_args_list[0]
    assert call_args[0][0] == "browser/login:frame"
    frame_data = call_args[0][1]
    assert "imageBase64" in frame_data
    assert "url" in frame_data
    assert "profile" in frame_data
    assert "pageTitle" in frame_data
    assert "elements" in frame_data
    assert frame_data["profile"] == "test"


@pytest.mark.asyncio
async def test_screenshot_loop_stops_on_closed_page(login_manager, mock_gateway):
    mock_page = MockPage()
    session_id = "login-test"
    login_manager._browser._pages[session_id] = mock_page

    task = asyncio.create_task(
        login_manager._screenshot_loop("test", session_id, interval_ms=50)
    )

    await asyncio.sleep(0.05)
    mock_page._closed = True
    await asyncio.sleep(0.1)

    assert task.done()


@pytest.mark.asyncio
async def test_send_input_success(login_manager):
    mock_page = MockPage()
    session_id = "login-test-profile"
    login_manager._flow_sessions["test-profile"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.send_login_input(
        profile="test-profile",
        ref=1,
        text="my-password",
    )

    assert result["success"] is True
    assert result["ref"] == 1

    locator = mock_page.locator("#email").first
    locator.fill.assert_called_once_with("")
    locator.type.assert_called_once_with("my-password", delay=50)


@pytest.mark.asyncio
async def test_send_input_no_active_flow(login_manager):
    result = await login_manager.send_login_input(
        profile="nonexistent",
        ref=1,
        text="password",
    )

    assert result["success"] is False
    assert "No active login flow" in result["error"]


@pytest.mark.asyncio
async def test_send_input_page_closed(login_manager):
    mock_page = MockPage()
    mock_page._closed = True
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.send_login_input(
        profile="test",
        ref=1,
        text="password",
    )

    assert result["success"] is False
    assert "Login page closed" in result["error"]


@pytest.mark.asyncio
async def test_send_input_stale_ref(login_manager):
    mock_page = MockPage()
    mock_page.evaluate = AsyncMock(return_value=None)
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.send_login_input(
        profile="test",
        ref=999,
        text="password",
    )

    assert result["success"] is False
    assert "Ref [999] not found" in result["error"]
    assert "page may have changed" in result["error"]


@pytest.mark.asyncio
async def test_send_input_type_failure(login_manager):
    mock_page = MockPage()
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    locator = mock_page.locator("#email").first
    locator.type.side_effect = Exception("Element not interactable")

    result = await login_manager.send_login_input(
        profile="test",
        ref=1,
        text="password",
    )

    assert result["success"] is False
    assert "Type into ref [1] failed" in result["error"]
    assert "Element not interactable" in result["error"]


@pytest.mark.asyncio
async def test_click_element_success(login_manager):
    mock_page = MockPage()
    session_id = "login-test-profile"
    login_manager._flow_sessions["test-profile"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.click_login_element(
        profile="test-profile",
        ref=2,
    )

    assert result["success"] is True
    assert result["ref"] == 2

    locator = mock_page.locator("#login-btn").first
    locator.click.assert_called_once_with(timeout=10_000)


@pytest.mark.asyncio
async def test_click_element_no_active_flow(login_manager):
    result = await login_manager.click_login_element(
        profile="nonexistent",
        ref=2,
    )

    assert result["success"] is False
    assert "No active login flow" in result["error"]


@pytest.mark.asyncio
async def test_click_element_stale_ref(login_manager):
    mock_page = MockPage()
    mock_page.evaluate = AsyncMock(return_value=None)
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.click_login_element(
        profile="test",
        ref=999,
    )

    assert result["success"] is False
    assert "Ref [999] not found" in result["error"]


@pytest.mark.asyncio
async def test_click_element_click_failure(login_manager):
    mock_page = MockPage()
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    locator = mock_page.locator("#login-btn").first
    locator.click.side_effect = Exception("Timeout waiting for element")

    result = await login_manager.click_login_element(
        profile="test",
        ref=2,
    )

    assert result["success"] is False
    assert "Click ref [2] failed" in result["error"]
    assert "Timeout waiting for element" in result["error"]


@pytest.mark.asyncio
async def test_stop_flow_authenticated(login_manager, mock_gateway, mock_profile_manager):
    mock_page = MockPage()
    mock_page.url = "https://gmail.com/inbox"
    mock_page.evaluate = AsyncMock(return_value=True)
    session_id = "login-gmail"
    login_manager._flow_sessions["gmail"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    mock_task = AsyncMock()
    mock_task.cancel = MagicMock()
    login_manager._active_flows["gmail"] = mock_task

    result = await login_manager.stop_login_flow("gmail")

    assert result["success"] is True
    assert result["authenticated"] is True
    assert result["domain"] == "gmail.com"

    mock_profile_manager.add_authenticated_domain.assert_called_once_with("gmail", "gmail.com")

    mock_gateway.emit_event.assert_called_once_with(
        "browser/login:end",
        {
            "profile": "gmail",
            "authenticated": True,
            "domain": "gmail.com",
        },
    )

    assert "gmail" not in login_manager._active_flows
    assert "gmail" not in login_manager._flow_sessions


@pytest.mark.asyncio
async def test_stop_flow_unauthenticated(login_manager, mock_gateway, mock_profile_manager):
    mock_page = MockPage()
    mock_page.url = "https://gmail.com/login"
    mock_page.evaluate = AsyncMock(return_value=False)
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.stop_login_flow("test")

    assert result["success"] is True
    assert result["authenticated"] is False
    assert result["domain"] == "gmail.com"

    mock_profile_manager.add_authenticated_domain.assert_not_called()

    mock_gateway.emit_event.assert_called_once_with(
        "browser/login:end",
        {
            "profile": "test",
            "authenticated": False,
            "domain": "gmail.com",
        },
    )


@pytest.mark.asyncio
async def test_stop_flow_no_page(login_manager, mock_gateway):
    result = await login_manager.stop_login_flow("nonexistent")

    assert result["success"] is True
    assert result["authenticated"] is False
    assert result["domain"] == ""

    mock_gateway.emit_event.assert_called_once()


@pytest.mark.asyncio
async def test_stop_cancels_streaming_task(login_manager):
    mock_page = MockPage()
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    task = asyncio.create_task(
        login_manager._screenshot_loop("test", session_id, interval_ms=100)
    )
    login_manager._active_flows["test"] = task

    await asyncio.sleep(0.05)

    result = await login_manager.stop_login_flow("test")

    assert result["success"] is True
    assert task.done()  # cancelled or finished
    assert "test" not in login_manager._active_flows


@pytest.mark.asyncio
async def test_shutdown(login_manager, mock_gateway):
    mock_page1 = MockPage()
    mock_page2 = MockPage()
    session_id1 = "login-profile1"
    session_id2 = "login-profile2"
    login_manager._flow_sessions["profile1"] = session_id1
    login_manager._flow_sessions["profile2"] = session_id2
    login_manager._browser._pages[session_id1] = mock_page1
    login_manager._browser._pages[session_id2] = mock_page2

    task1 = asyncio.create_task(
        login_manager._screenshot_loop("profile1", session_id1, interval_ms=100)
    )
    task2 = asyncio.create_task(
        login_manager._screenshot_loop("profile2", session_id2, interval_ms=100)
    )
    login_manager._active_flows["profile1"] = task1
    login_manager._active_flows["profile2"] = task2

    await asyncio.sleep(0.05)

    await login_manager.shutdown()

    assert task1.done()  # cancelled or finished
    assert task2.done()  # cancelled or finished
    assert len(login_manager._active_flows) == 0
    assert len(login_manager._flow_sessions) == 0


@pytest.mark.asyncio
async def test_shutdown_handles_task_exceptions(login_manager):
    async def failing_task():
        await asyncio.sleep(1)
        raise RuntimeError("Task error")

    task = asyncio.create_task(failing_task())
    login_manager._active_flows["test"] = task
    login_manager._flow_sessions["test"] = "session"

    await asyncio.sleep(0.01)

    await login_manager.shutdown()

    assert len(login_manager._active_flows) == 0
    assert len(login_manager._flow_sessions) == 0


@pytest.mark.asyncio
async def test_screenshot_loop_handles_evaluate_error(login_manager, mock_gateway):
    mock_page = MockPage()
    mock_page.evaluate = AsyncMock(side_effect=Exception("JS error"))
    session_id = "login-test"
    login_manager._browser._pages[session_id] = mock_page

    task = asyncio.create_task(
        login_manager._screenshot_loop("test", session_id, interval_ms=100)
    )

    await asyncio.sleep(0.15)

    assert task.done()


@pytest.mark.asyncio
async def test_screenshot_loop_handles_screenshot_error(login_manager, mock_gateway):
    mock_page = MockPage()
    mock_page.screenshot = AsyncMock(side_effect=Exception("Screenshot failed"))
    session_id = "login-test"
    login_manager._browser._pages[session_id] = mock_page

    task = asyncio.create_task(
        login_manager._screenshot_loop("test", session_id, interval_ms=100)
    )

    await asyncio.sleep(0.15)

    assert task.done()


@pytest.mark.asyncio
async def test_stop_flow_handles_evaluate_error(login_manager, mock_gateway, mock_profile_manager):
    mock_page = MockPage()
    mock_page.evaluate = AsyncMock(side_effect=Exception("Auth check failed"))
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.stop_login_flow("test")

    assert result["success"] is True
    assert result["authenticated"] is False
    mock_profile_manager.add_authenticated_domain.assert_not_called()


@pytest.mark.asyncio
async def test_stop_flow_handles_urlparse_error(login_manager, mock_gateway):
    mock_page = MockPage()
    mock_page.url = "not-a-valid-url"
    mock_page.evaluate = AsyncMock(return_value=True)
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.stop_login_flow("test")

    assert result["success"] is True
    assert result["domain"] == ""


@pytest.mark.asyncio
async def test_send_input_scroll_failure_continues(login_manager):
    mock_page = MockPage()
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    locator = mock_page.locator("#email").first
    locator.scroll_into_view_if_needed.side_effect = Exception("Scroll failed")

    result = await login_manager.send_login_input(
        profile="test",
        ref=1,
        text="password",
    )

    assert result["success"] is True
    locator.fill.assert_called_once_with("")
    locator.type.assert_called_once_with("password", delay=50)


@pytest.mark.asyncio
async def test_click_element_scroll_failure_continues(login_manager):
    mock_page = MockPage()
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    locator = mock_page.locator("#login-btn").first
    locator.scroll_into_view_if_needed.side_effect = Exception("Scroll failed")

    result = await login_manager.click_login_element(
        profile="test",
        ref=2,
    )

    assert result["success"] is True
    locator.click.assert_called_once_with(timeout=10_000)


@pytest.mark.asyncio
async def test_click_element_wait_for_load_failure_continues(login_manager):
    mock_page = MockPage()
    mock_page.wait_for_load_state = AsyncMock(side_effect=Exception("Timeout"))
    session_id = "login-test"
    login_manager._flow_sessions["test"] = session_id
    login_manager._browser._pages[session_id] = mock_page

    result = await login_manager.click_login_element(
        profile="test",
        ref=2,
    )

    assert result["success"] is True


@pytest.mark.asyncio
async def test_start_flow_custom_interval(login_manager, mock_browser, mock_profile_manager):
    mock_browser.execute.return_value = ToolResult(success=True, output="", error=None)

    result = await login_manager.start_login_flow(
        profile="test-profile",
        url="https://example.com/login",
        interval_ms=500,
    )

    assert result["success"] is True

    task = login_manager._active_flows["test-profile"]
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
