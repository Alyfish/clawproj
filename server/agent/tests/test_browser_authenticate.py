"""Tests for browser authenticate action wiring to LoginHandler."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.agent.tools.browser_cdp import CDPBrowserTool


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tool():
    """CDPBrowserTool with no LoginHandler wired."""
    return CDPBrowserTool()


@pytest.fixture
def mock_page():
    """Minimal mock Playwright Page."""
    page = AsyncMock()
    page.url = "https://example.com"
    page.is_closed = MagicMock(return_value=False)
    page.evaluate = AsyncMock(return_value=None)
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    return page


@pytest.fixture
def mock_login_handler():
    """Mock LoginHandler with handle_login_wall."""
    handler = MagicMock()
    handler.handle_login_wall = AsyncMock(return_value=True)
    handler.get_login_url = MagicMock(side_effect=lambda d: f"https://{d}/login")
    return handler


@pytest.fixture
def tool_with_handler(mock_login_handler):
    """CDPBrowserTool with LoginHandler wired."""
    t = CDPBrowserTool()
    t.set_login_handler(mock_login_handler)
    return t


# ── Authenticate action tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_authenticate_delegates_to_login_handler(
    tool_with_handler, mock_page, mock_login_handler,
):
    """Wire LoginHandler mock, call _authenticate, verify handle_login_wall called."""
    result = await tool_with_handler._authenticate(
        mock_page, {"domain": "amazon.com", "reason": "Need to check orders"},
    )
    mock_login_handler.handle_login_wall.assert_awaited_once_with(
        mock_page,
        "amazon.com",
        profile="default",
        session_id="default",
        reason="Need to check orders",
    )
    assert result["success"] is True
    assert result["domain"] == "amazon.com"


@pytest.mark.asyncio
async def test_authenticate_success_message(
    tool_with_handler, mock_page, mock_login_handler,
):
    """LoginHandler returns True -> message says 'Successfully authenticated'."""
    mock_login_handler.handle_login_wall.return_value = True
    result = await tool_with_handler._authenticate(
        mock_page, {"domain": "github.com"},
    )
    assert result["success"] is True
    assert "Successfully authenticated" in result["message"]
    assert "github.com" in result["message"]


@pytest.mark.asyncio
async def test_authenticate_interactive_fallback_message(
    tool_with_handler, mock_page, mock_login_handler,
):
    """LoginHandler returns False -> message mentions 'check your phone'."""
    mock_login_handler.handle_login_wall.return_value = False
    result = await tool_with_handler._authenticate(
        mock_page, {"domain": "google.com"},
    )
    assert result["success"] is False
    assert "phone" in result["message"].lower()
    assert "google.com" in result["message"]


@pytest.mark.asyncio
async def test_authenticate_error_handling(
    tool_with_handler, mock_page, mock_login_handler,
):
    """LoginHandler raises exception -> error message returned, no crash."""
    mock_login_handler.handle_login_wall.side_effect = RuntimeError("connection lost")
    result = await tool_with_handler._authenticate(
        mock_page, {"domain": "example.com"},
    )
    assert result["success"] is False
    assert "error" in result
    assert "connection lost" in result["error"]


@pytest.mark.asyncio
async def test_authenticate_missing_domain(tool_with_handler, mock_page):
    """No domain param -> error message about required parameter."""
    result = await tool_with_handler._authenticate(mock_page, {})
    assert result["success"] is False
    assert "domain" in result["error"].lower()


@pytest.mark.asyncio
async def test_authenticate_no_login_handler_uses_legacy(tool, mock_page):
    """_login_handler is None -> falls through to _authenticate_legacy."""
    # Patch _authenticate_legacy to verify it gets called
    legacy_result = {"success": True, "status": "legacy_called"}
    tool._authenticate_legacy = AsyncMock(return_value=legacy_result)

    result = await tool._authenticate(mock_page, {"domain": "example.com"})
    tool._authenticate_legacy.assert_awaited_once()
    # Verify URL constructed from domain
    call_args = tool._authenticate_legacy.call_args
    params = call_args[0][1]
    assert "https://example.com" in params["url"]
    assert result == legacy_result


# ── Login action tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_action_tries_login_handler_first(
    tool_with_handler, mock_page, mock_login_handler,
):
    """Call _login with URL, verify LoginHandler tried before LoginFlowManager."""
    mock_login_handler.handle_login_wall.return_value = True
    result = await tool_with_handler._login(
        mock_page, {"url": "https://github.com/login"},
    )
    mock_login_handler.handle_login_wall.assert_awaited_once()
    assert result["success"] is True
    assert result["domain"] == "github.com"


@pytest.mark.asyncio
async def test_login_action_falls_through_without_login_handler(tool, mock_page):
    """_login_handler is None -> goes directly to interactive LoginFlowManager."""
    # No login_flow_manager either -> should get error
    result = await tool._login(mock_page, {"url": "https://example.com"})
    assert result["success"] is False
    assert "not configured" in result["error"]
