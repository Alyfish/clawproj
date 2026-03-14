"""
Tests for CDPBrowserTool.

Covers:
- Tool initialization and properties
- CDP connection lifecycle (connect, reconnect, retry with backoff)
- All 11 action handlers
- Checkpoint detection (payment, CAPTCHA, 2FA, form submit)
- SSRF protection
- Session management (create, reuse, close)
- Error handling (unknown action, timeout, connection failure)
- Shutdown and cleanup
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlunparse

import pytest

from server.agent.browser_profiles import BrowserProfileManager
from server.agent.tools.browser_cdp import CDPBrowserTool
from server.agent.tools.tool_registry import ToolResult


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tool():
    """Create a CDPBrowserTool instance."""
    return CDPBrowserTool()


@pytest.fixture
def mock_page():
    """Create a mock Playwright Page."""
    page = AsyncMock()
    page.url = "https://example.com"
    page.title = AsyncMock(return_value="Example")
    page.is_closed = MagicMock(return_value=False)
    page.goto = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n")
    page.evaluate = AsyncMock(return_value=None)
    page.locator = MagicMock()
    page.locator.return_value.click = AsyncMock()
    page.locator.return_value.fill = AsyncMock()
    page.locator.return_value.inner_text = AsyncMock(return_value="Hello World")
    page.locator.return_value.scroll_into_view_if_needed = AsyncMock()
    page.get_by_text = MagicMock()
    page.get_by_text.return_value.first = AsyncMock()
    page.get_by_text.return_value.first.click = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.go_back = AsyncMock()
    page.set_default_timeout = MagicMock()
    page.set_default_navigation_timeout = MagicMock()
    return page


@pytest.fixture
def mock_context():
    """Create a mock BrowserContext."""
    ctx = AsyncMock()
    ctx.cookies = AsyncMock(return_value=[{"name": "sid", "value": "abc123"}])
    ctx.new_page = AsyncMock()
    ctx.close = AsyncMock()
    return ctx


@pytest.fixture
def mock_browser():
    """Create a mock Browser (CDP connection)."""
    browser = AsyncMock()
    browser.is_connected = MagicMock(return_value=True)
    browser.new_context = AsyncMock()
    browser.close = AsyncMock()
    return browser


def _wire_tool(tool, mock_browser, mock_context, mock_page):
    """Wire mock objects into the tool's internal state."""
    tool._browser = mock_browser
    tool._playwright = AsyncMock()
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page
    # Pre-wire a default session
    tool._contexts["default"] = mock_context
    tool._pages["default"] = mock_page


# ── Init tests ───────────────────────────────────────────────────────


class TestInit:
    def test_name_is_browser(self, tool):
        assert tool.name == "browser"

    def test_default_cdp_url(self, tool):
        assert "localhost:3000" in tool._cdp_url

    def test_cdp_url_from_env(self, monkeypatch):
        monkeypatch.setenv("BROWSER_CDP_URL", "ws://custom:9222")
        t = CDPBrowserTool()
        assert t._cdp_url == "ws://custom:9222"

    def test_parameters_has_all_actions(self, tool):
        actions = tool.parameters["action"]["enum"]
        assert len(actions) == 16  # 11 original + snapshot + click_ref + type_ref + select_ref + authenticate
        assert "navigate" in actions
        assert "evaluate_js" in actions
        assert "get_cookies" in actions
        assert "snapshot" in actions
        assert "click_ref" in actions
        assert "type_ref" in actions
        assert "select_ref" in actions

    def test_has_session_id_param(self, tool):
        assert "session_id" in tool.parameters
        assert tool.parameters["session_id"]["required"] is False


# ── Connection tests ─────────────────────────────────────────────────


class TestConnection:
    @pytest.mark.asyncio
    async def test_lazy_connect_on_first_execute(self, tool, mock_browser, mock_context, mock_page):
        """Connection is established on first execute() call."""
        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_pw_cm = AsyncMock()
        mock_pw_cm.start = AsyncMock(return_value=mock_pw_instance)

        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        # Return False for checkpoint detection evals
        mock_page.evaluate = AsyncMock(return_value=False)

        with patch("server.agent.tools.browser_cdp._import_playwright"):
            with patch("server.agent.tools.browser_cdp._async_playwright", return_value=mock_pw_cm):
                result = await tool.execute(action="current_url")

        assert result.success
        mock_pw_instance.chromium.connect_over_cdp.assert_called_once()

    @pytest.mark.asyncio
    async def test_reuse_connection(self, tool, mock_browser, mock_context, mock_page):
        """Second execute reuses existing connection."""
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        await tool.execute(action="current_url")
        await tool.execute(action="current_url")

        # new_context should not be called again (page already exists)
        mock_browser.new_context.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconnect_on_disconnect(self, tool, mock_page, mock_context):
        """Reconnects when browser.is_connected() returns False."""
        # First browser is disconnected
        disconnected_browser = AsyncMock()
        disconnected_browser.is_connected = MagicMock(return_value=False)
        tool._browser = disconnected_browser
        tool._playwright = AsyncMock()

        # New browser that works
        new_browser = AsyncMock()
        new_browser.is_connected = MagicMock(return_value=True)
        new_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.connect_over_cdp = AsyncMock(return_value=new_browser)
        mock_pw_cm = AsyncMock()
        mock_pw_cm.start = AsyncMock(return_value=mock_pw_instance)

        with patch("server.agent.tools.browser_cdp._import_playwright"):
            with patch("server.agent.tools.browser_cdp._async_playwright", return_value=mock_pw_cm):
                result = await tool.execute(action="current_url")

        assert result.success
        mock_pw_instance.chromium.connect_over_cdp.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_with_backoff(self, tool):
        """Retries connection with exponential backoff on failure."""
        mock_pw_instance = AsyncMock()
        mock_pw_instance.chromium.connect_over_cdp = AsyncMock(
            side_effect=[Exception("fail1"), Exception("fail2"), Exception("fail3")]
        )
        mock_pw_cm = AsyncMock()
        mock_pw_cm.start = AsyncMock(return_value=mock_pw_instance)

        with patch("server.agent.tools.browser_cdp._import_playwright"):
            with patch("server.agent.tools.browser_cdp._async_playwright", return_value=mock_pw_cm):
                with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result = await tool.execute(action="current_url")

        assert not result.success
        assert "Failed to connect" in result.error
        assert mock_sleep.call_count == 3
        # Check exponential backoff delays: 1s, 2s, 4s
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0, 4.0]


# ── DNS mock helpers ─────────────────────────────────────────────────


def _mock_dns_public(*args, **kwargs):
    """Mock DNS returning a public IP."""
    import socket as _socket
    return [(_socket.AF_INET, _socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


def _mock_dns_private(*args, **kwargs):
    """Mock DNS returning a private IP."""
    import socket as _socket
    return [(_socket.AF_INET, _socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]


# ── Action tests ─────────────────────────────────────────────────────


class TestActions:
    @pytest.mark.asyncio
    async def test_navigate(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        with patch("socket.getaddrinfo", side_effect=_mock_dns_public):
            result = await tool.execute(action="navigate", params={"url": "https://example.com"})
        assert result.success
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is True
        mock_page.goto.assert_called()

    @pytest.mark.asyncio
    async def test_navigate_blocks_ssrf(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="navigate", params={"url": "http://localhost:8080/admin"}
        )
        assert result.success  # ToolResult is success, but the action result says blocked
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False
        assert "Blocked" in output["error"] or "blocked" in output["error"].lower()

    @pytest.mark.asyncio
    async def test_navigate_blocks_private_ip(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="navigate", params={"url": "http://192.168.1.1/admin"}
        )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False

    @pytest.mark.asyncio
    async def test_click(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(action="click", params={"selector": "#btn"})
        assert result.success
        mock_page.locator.assert_called_with("#btn")

    @pytest.mark.asyncio
    async def test_type(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="type", params={"selector": "#email", "text": "test@example.com"}
        )
        assert result.success
        mock_page.locator.assert_called_with("#email")

    @pytest.mark.asyncio
    async def test_extract_text_with_selector(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="extract_text", params={"selector": ".content"}
        )
        assert result.success
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["text"] == "Hello World"

    @pytest.mark.asyncio
    async def test_extract_text_full_page(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        # 3 checkpoint evals (card_fields, captcha, 2fa) then extract_text body eval
        mock_page.evaluate = AsyncMock(side_effect=[False, False, False, "Full page text"])

        result = await tool.execute(action="extract_text", params={})
        assert result.success

    @pytest.mark.asyncio
    async def test_screenshot(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)
        mock_page.screenshot = AsyncMock(return_value=b"\x89PNG\r\nfakedata")

        result = await tool.execute(action="screenshot", params={})
        assert result.success
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["format"] == "png"
        assert "data" in output

    @pytest.mark.asyncio
    async def test_scroll(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="scroll", params={"direction": "down", "amount": 500}
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_wait_for(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="wait_for", params={"selector": "#loaded"}
        )
        assert result.success
        mock_page.wait_for_selector.assert_called()

    @pytest.mark.asyncio
    async def test_evaluate_js(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        # 3 checkpoint evals (card_fields, captcha, 2fa), then the actual eval
        mock_page.evaluate = AsyncMock(
            side_effect=[False, False, False, {"key": "value"}]
        )

        result = await tool.execute(
            action="evaluate_js", params={"expression": "({key: 'value'})"}
        )
        assert result.success
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["result"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_cookies(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(action="get_cookies", params={})
        assert result.success
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["cookies"] == [{"name": "sid", "value": "abc123"}]

    @pytest.mark.asyncio
    async def test_back(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(action="back", params={})
        assert result.success
        mock_page.go_back.assert_called()

    @pytest.mark.asyncio
    async def test_current_url(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(action="current_url", params={})
        assert result.success
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["url"] == "https://example.com"
        assert output["title"] == "Example"


# ── Checkpoint detection tests ───────────────────────────────────────


class TestCheckpointDetection:
    @pytest.mark.asyncio
    async def test_detects_payment_page_by_url(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.url = "https://shop.com/checkout/step1"
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(action="click", params={"selector": "#next"})
        assert not result.success
        assert "CHECKPOINT" in result.error
        assert "Payment" in result.error

    @pytest.mark.asyncio
    async def test_detects_payment_page_by_card_fields(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.url = "https://shop.com/step2"
        # First evaluate (card fields) returns True
        mock_page.evaluate = AsyncMock(return_value=True)

        result = await tool.execute(action="click", params={"selector": "#next"})
        assert not result.success
        assert "CHECKPOINT" in result.error

    @pytest.mark.asyncio
    async def test_detects_captcha(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.url = "https://site.com/login"
        # card fields: False, captcha: True (detected before 2fa check)
        mock_page.evaluate = AsyncMock(side_effect=[False, True])

        with patch("socket.getaddrinfo", side_effect=_mock_dns_public):
            result = await tool.execute(action="navigate", params={"url": "https://site.com/login"})
        assert not result.success
        assert "CAPTCHA" in result.error

    @pytest.mark.asyncio
    async def test_detects_2fa(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.url = "https://site.com/2fa"
        # card fields: False, captcha: False, 2fa: True
        mock_page.evaluate = AsyncMock(side_effect=[False, False, True])

        with patch("socket.getaddrinfo", side_effect=_mock_dns_public):
            result = await tool.execute(action="navigate", params={"url": "https://site.com/page"})
        assert not result.success
        assert "2FA" in result.error

    @pytest.mark.asyncio
    async def test_checkpoint_failure_fails_safe(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.url = "https://site.com"
        mock_page.evaluate = AsyncMock(side_effect=Exception("eval crashed"))

        with patch("socket.getaddrinfo", side_effect=_mock_dns_public):
            result = await tool.execute(action="navigate", params={"url": "https://site.com"})
        assert not result.success
        assert "safety fallback" in (result.error or "").lower() or "CHECKPOINT" in (result.error or "")


# ── Session management tests ─────────────────────────────────────────


class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_creates_new_context_per_session(self, tool, mock_browser, mock_context, mock_page):
        tool._browser = mock_browser
        tool._playwright = AsyncMock()

        ctx1 = AsyncMock()
        page1 = AsyncMock()
        page1.is_closed = MagicMock(return_value=False)
        page1.set_default_timeout = MagicMock()
        page1.set_default_navigation_timeout = MagicMock()
        ctx1.new_page = AsyncMock(return_value=page1)

        ctx2 = AsyncMock()
        page2 = AsyncMock()
        page2.is_closed = MagicMock(return_value=False)
        page2.set_default_timeout = MagicMock()
        page2.set_default_navigation_timeout = MagicMock()
        ctx2.new_page = AsyncMock(return_value=page2)

        mock_browser.new_context = AsyncMock(side_effect=[ctx1, ctx2])

        p1 = await tool._get_page("session_a")
        p2 = await tool._get_page("session_b")

        assert p1 is not p2
        assert mock_browser.new_context.call_count == 2

    @pytest.mark.asyncio
    async def test_reuses_context_for_same_session(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)

        p1 = await tool._get_page("default")
        p2 = await tool._get_page("default")

        assert p1 is p2

    @pytest.mark.asyncio
    async def test_close_context(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)

        await tool.close_context("default")

        assert "default" not in tool._pages
        assert "default" not in tool._contexts
        mock_context.close.assert_called_once()


# ── Error handling tests ─────────────────────────────────────────────


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_unknown_action(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)

        result = await tool.execute(action="fly_to_moon", params={})
        assert not result.success
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_missing_action(self, tool):
        result = await tool.execute(action="", params={})
        assert not result.success
        assert "Missing required parameter" in result.error

    @pytest.mark.asyncio
    async def test_action_exception_handled(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)
        mock_page.goto = AsyncMock(side_effect=Exception("Network error"))

        with patch("socket.getaddrinfo", side_effect=_mock_dns_public):
            result = await tool.execute(
                action="navigate", params={"url": "https://example.com"}
            )
        # The navigate handler catches the error internally
        assert result.success  # ToolResult succeeds, action data contains error
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False


# ── SSRF protection tests (integrated via BrowserSecurityPolicy) ─────


class TestSSRF:
    @pytest.mark.asyncio
    async def test_navigate_allows_public_url(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        with patch("socket.getaddrinfo", side_effect=_mock_dns_public):
            result = await tool.execute(action="navigate", params={"url": "https://example.com"})
        assert result.success
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is True

    @pytest.mark.asyncio
    async def test_navigate_blocks_private_ip(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="navigate", params={"url": "http://192.168.1.1/admin"}
        )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False
        assert "Blocked" in output["error"]

    @pytest.mark.asyncio
    async def test_navigate_blocks_localhost(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="navigate", params={"url": "http://localhost:8080/admin"}
        )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False

    @pytest.mark.asyncio
    async def test_navigate_blocks_dns_rebinding(self, tool, mock_browser, mock_context, mock_page):
        """Domain resolving to private IP is blocked (DNS rebinding defense)."""
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        with patch("socket.getaddrinfo", side_effect=_mock_dns_private):
            result = await tool.execute(
                action="navigate", params={"url": "https://evil.com/steal"}
            )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False
        assert "10.0.0.1" in output["error"]

    @pytest.mark.asyncio
    async def test_navigate_blocks_metadata_endpoint(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(
            action="navigate",
            params={"url": "http://169.254.169.254/latest/meta-data/"},
        )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False

    @pytest.mark.asyncio
    async def test_navigate_post_redirect_blocked(self, tool, mock_browser, mock_context, mock_page):
        """If navigation redirects to a private IP, it should be blocked."""
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)
        # After goto, page.url returns a private IP
        mock_page.url = "http://10.0.0.1/internal"

        with patch("socket.getaddrinfo", side_effect=_mock_dns_public):
            result = await tool.execute(
                action="navigate", params={"url": "https://redirect.example.com"}
            )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False
        assert "redirect" in output["error"].lower()

    @pytest.mark.asyncio
    async def test_navigate_rate_limiting(self, tool, mock_browser, mock_context, mock_page):
        """Navigation is blocked after exceeding the per-session limit."""
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        # Set nav count to the limit
        tool._nav_counts["default"] = tool._security.MAX_NAVIGATIONS_PER_SESSION

        result = await tool.execute(
            action="navigate", params={"url": "https://example.com"}
        )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False
        assert "limit" in output["error"].lower()

    @pytest.mark.asyncio
    async def test_evaluate_js_size_limit(self, tool, mock_browser, mock_context, mock_page):
        """Large JS expressions are blocked."""
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        big_js = "x" * 20_000
        result = await tool.execute(
            action="evaluate_js", params={"expression": big_js}
        )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False
        assert "too large" in output["error"].lower()

    @pytest.mark.asyncio
    async def test_navigate_blocks_download(self, tool, mock_browser, mock_context, mock_page):
        """URLs pointing to dangerous file extensions are blocked."""
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        with patch("socket.getaddrinfo", side_effect=_mock_dns_public):
            result = await tool.execute(
                action="navigate", params={"url": "https://example.com/malware.exe"}
            )
        output = json.loads(result.output.split("\n\n[Screenshot")[0])
        assert output["success"] is False
        assert ".exe" in output["error"]


# ── Shutdown tests ───────────────────────────────────────────────────


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_closes_all(self, tool, mock_browser, mock_context, mock_page):
        _wire_tool(tool, mock_browser, mock_context, mock_page)

        await tool.shutdown()

        assert tool._browser is None
        assert tool._playwright is None
        assert len(tool._contexts) == 0
        assert len(tool._pages) == 0
        mock_context.close.assert_called()
        mock_browser.close.assert_called()

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self, tool):
        """Calling shutdown on a fresh tool doesn't raise."""
        await tool.shutdown()
        await tool.shutdown()  # Should not raise


# ── Profile switching tests ─────────────────────────────────────────


class TestProfileSwitching:
    @pytest.fixture
    def profile_manager(self, tmp_path):
        """Create a BrowserProfileManager with temp directory."""
        return BrowserProfileManager(base_dir=str(tmp_path))

    @pytest.fixture
    def tool_with_profiles(self, profile_manager):
        """CDPBrowserTool with profile manager."""
        return CDPBrowserTool(profile_manager=profile_manager)

    def test_no_profile_manager_skips_switching(self):
        """CDPBrowserTool() with no profile_manager, profile param ignored."""
        tool = CDPBrowserTool()
        assert tool._profile_manager is None
        assert tool._active_profile == "default"

    def test_cdp_url_includes_user_data_dir(self, tool_with_profiles, profile_manager):
        """_build_cdp_url() includes --user-data-dir in launch args."""
        profile_manager.create_profile("gmail")
        url = tool_with_profiles._build_cdp_url("gmail")
        decoded = unquote(url)
        assert "--user-data-dir=" in decoded
        assert "gmail" in decoded
        assert "launch=" in url

    @pytest.mark.asyncio
    async def test_switch_creates_default_profile(self, tool_with_profiles, profile_manager):
        """Switching to 'default' auto-creates the default profile."""
        # Start from a non-default profile to trigger the switch path
        tool_with_profiles._active_profile = "other"
        await tool_with_profiles._switch_profile_if_needed("default")
        assert tool_with_profiles._active_profile == "default"
        assert profile_manager.get_profile("default") is not None

    @pytest.mark.asyncio
    async def test_switch_same_profile_noop(self, tool_with_profiles, profile_manager):
        """Switching to the same profile does nothing."""
        profile_manager.create_profile("gmail")
        tool_with_profiles._active_profile = "gmail"
        # Should return without any cleanup
        await tool_with_profiles._switch_profile_if_needed("gmail")
        assert tool_with_profiles._active_profile == "gmail"

    @pytest.mark.asyncio
    async def test_switch_nonexistent_profile_raises(self, tool_with_profiles):
        """Switching to a non-existent profile raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            await tool_with_profiles._switch_profile_if_needed("nonexistent")

    @pytest.mark.asyncio
    async def test_switch_disconnects_and_reconnects(self, tool_with_profiles, profile_manager, mock_browser, mock_context, mock_page):
        """Switching profiles disconnects the current browser."""
        profile_manager.create_profile("work")
        # Wire up the tool as if it's connected
        tool_with_profiles._browser = mock_browser
        tool_with_profiles._playwright = AsyncMock()
        tool_with_profiles._active_profile = "default"

        await tool_with_profiles._switch_profile_if_needed("work")

        assert tool_with_profiles._active_profile == "work"
        assert tool_with_profiles._browser is None  # cleanup was called
        decoded_url = unquote(tool_with_profiles._cdp_url)
        assert "--user-data-dir=" in decoded_url
        assert "work" in decoded_url

    @pytest.mark.asyncio
    async def test_execute_with_profile_no_manager(self, tool, mock_browser, mock_context, mock_page):
        """Execute with profile param but no manager — profile ignored."""
        _wire_tool(tool, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool.execute(action="current_url", params={}, profile="gmail")
        assert result.success  # Works fine, profile param ignored

    @pytest.mark.asyncio
    async def test_execute_with_unknown_profile_fails(self, tool_with_profiles, mock_browser, mock_context, mock_page):
        """Execute with unknown profile returns error."""
        _wire_tool(tool_with_profiles, mock_browser, mock_context, mock_page)
        mock_page.evaluate = AsyncMock(return_value=False)

        result = await tool_with_profiles.execute(
            action="current_url", params={}, profile="nonexistent"
        )
        assert not result.success
        assert "not found" in result.error
