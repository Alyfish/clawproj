"""
Tests for snapshot and ref-based interaction actions in CDPBrowserTool.

Covers:
- _snapshot: DOM walker that returns numbered interactive elements
- _resolve_ref: Look up snapshot refs from window.__clawbot_refs
- _click_ref: Click element by snapshot ref number
- _type_ref: Type text into element by ref number
- _select_ref: Select option in dropdown by ref number
- _login: Start interactive login flow (streams to user's phone)
- set_login_flow_manager: Wire LoginFlowManager after construction

These are the ref-based interaction methods added to CDPBrowserTool
to make browser automation more reliable than CSS selectors.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock
from typing import Any

import pytest

from server.agent.tools.browser_cdp import CDPBrowserTool


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tool():
    """Create a CDPBrowserTool instance with mocked environment."""
    # Set BROWSER_CDP_URL in environment to avoid errors
    os.environ["BROWSER_CDP_URL"] = "ws://localhost:3000?token=test"
    return CDPBrowserTool()


@pytest.fixture
def mock_page():
    """Create a mock Playwright Page with locator support."""
    page = AsyncMock()
    page.url = "https://example.com"
    page.title = AsyncMock(return_value="Example")
    page.evaluate = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    # Mock locator chain: page.locator(selector).first
    mock_locator = MagicMock()
    mock_first = MagicMock()
    mock_first.click = AsyncMock()
    mock_first.scroll_into_view_if_needed = AsyncMock()
    mock_first.fill = AsyncMock()
    mock_first.type = AsyncMock()
    mock_first.select_option = AsyncMock()
    mock_locator.first = mock_first
    page.locator = MagicMock(return_value=mock_locator)

    return page


# ── Snapshot tests ───────────────────────────────────────────────────


class TestSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot_success(self, tool, mock_page):
        """Snapshot returns numbered interactive elements."""
        mock_page.evaluate.return_value = {
            "snapshot": "[Page] Test\n[1] button \"Submit\"",
            "elementCount": 1,
        }

        result = await tool._snapshot(mock_page, {})

        assert result["success"] is True
        assert result["snapshot"] == "[Page] Test\n[1] button \"Submit\""
        assert result["elementCount"] == 1
        mock_page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_snapshot_with_multiple_elements(self, tool, mock_page):
        """Snapshot returns multiple elements."""
        mock_page.evaluate.return_value = {
            "snapshot": "[Page] Login\n[1] input \"Email\"\n[2] input \"Password\"\n[3] button \"Sign in\"",
            "elementCount": 3,
        }

        result = await tool._snapshot(mock_page, {})

        assert result["success"] is True
        assert result["elementCount"] == 3
        assert "Email" in result["snapshot"]
        assert "Password" in result["snapshot"]
        assert "Sign in" in result["snapshot"]

    @pytest.mark.asyncio
    async def test_snapshot_failure(self, tool, mock_page):
        """Snapshot handles evaluation errors."""
        mock_page.evaluate.side_effect = Exception("Page crashed")

        result = await tool._snapshot(mock_page, {})

        assert result["success"] is False
        assert "Snapshot failed" in result["error"]
        assert "Page crashed" in result["error"]

    @pytest.mark.asyncio
    async def test_snapshot_empty_page(self, tool, mock_page):
        """Snapshot handles pages with no interactive elements."""
        mock_page.evaluate.return_value = {
            "snapshot": "[Page] Empty\n",
            "elementCount": 0,
        }

        result = await tool._snapshot(mock_page, {})

        assert result["success"] is True
        assert result["elementCount"] == 0


# ── Resolve ref tests ────────────────────────────────────────────────


class TestResolveRef:
    @pytest.mark.asyncio
    async def test_resolve_ref_success(self, tool, mock_page):
        """Resolve ref returns element entry."""
        mock_page.evaluate.return_value = {
            "selector": "#btn",
            "tagName": "button",
            "description": "button Submit",
        }

        entry = await tool._resolve_ref(mock_page, 3)

        assert entry is not None
        assert entry["selector"] == "#btn"
        assert entry["tagName"] == "button"
        assert entry["description"] == "button Submit"
        # Verify JS_LOOKUP_REF was called with ref number
        assert mock_page.evaluate.call_count == 1

    @pytest.mark.asyncio
    async def test_resolve_ref_not_found(self, tool, mock_page):
        """Resolve ref returns None when ref doesn't exist."""
        mock_page.evaluate.return_value = None

        entry = await tool._resolve_ref(mock_page, 999)

        assert entry is None

    @pytest.mark.asyncio
    async def test_resolve_ref_evaluation_error(self, tool, mock_page):
        """Resolve ref returns None on evaluation error."""
        mock_page.evaluate.side_effect = Exception("DOM access error")

        entry = await tool._resolve_ref(mock_page, 5)

        assert entry is None


# ── Click ref tests ──────────────────────────────────────────────────


class TestClickRef:
    @pytest.mark.asyncio
    async def test_click_ref_success(self, tool, mock_page):
        """Click ref clicks element and waits for load."""
        # Mock resolve_ref to return an entry
        mock_page.evaluate.return_value = {
            "selector": "#submit-btn",
            "tagName": "button",
            "description": "button Submit",
        }

        result = await tool._click_ref(mock_page, {"ref": 3})

        assert result["success"] is True
        assert result["ref"] == 3
        assert result["clicked"] == "button Submit"

        # Verify locator was called with correct selector
        mock_page.locator.assert_called_once_with("#submit-btn")
        locator_first = mock_page.locator.return_value.first
        locator_first.scroll_into_view_if_needed.assert_called_once()
        locator_first.click.assert_called_once_with(timeout=10_000)
        mock_page.wait_for_load_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_click_ref_scroll_fails_continues(self, tool, mock_page):
        """Click ref continues if scroll fails."""
        mock_page.evaluate.return_value = {
            "selector": "#btn",
            "tagName": "button",
            "description": "button Click me",
        }

        locator_first = mock_page.locator.return_value.first
        locator_first.scroll_into_view_if_needed.side_effect = Exception("Scroll failed")

        result = await tool._click_ref(mock_page, {"ref": 1})

        # Should succeed despite scroll failure
        assert result["success"] is True
        locator_first.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_click_ref_wait_for_load_timeout(self, tool, mock_page):
        """Click ref succeeds even if wait_for_load_state times out."""
        mock_page.evaluate.return_value = {
            "selector": "#link",
            "tagName": "a",
            "description": "link Home",
        }
        mock_page.wait_for_load_state.side_effect = Exception("Timeout")

        result = await tool._click_ref(mock_page, {"ref": 2})

        # Should still succeed
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_click_ref_not_found(self, tool, mock_page):
        """Click ref returns error when ref doesn't exist."""
        mock_page.evaluate.return_value = None

        result = await tool._click_ref(mock_page, {"ref": 999})

        assert result["success"] is False
        assert "Ref [999] not found" in result["error"]
        assert "Re-run snapshot" in result["error"]

    @pytest.mark.asyncio
    async def test_click_ref_missing_param(self, tool, mock_page):
        """Click ref returns error when ref param is missing."""
        result = await tool._click_ref(mock_page, {})

        assert result["success"] is False
        assert "Missing required parameter: ref" in result["error"]

    @pytest.mark.asyncio
    async def test_click_ref_click_fails(self, tool, mock_page):
        """Click ref returns error when click fails."""
        mock_page.evaluate.return_value = {
            "selector": "#btn",
            "tagName": "button",
            "description": "button Submit",
        }
        locator_first = mock_page.locator.return_value.first
        locator_first.click.side_effect = Exception("Element is not clickable")

        result = await tool._click_ref(mock_page, {"ref": 5})

        assert result["success"] is False
        assert "Click ref [5] failed" in result["error"]
        assert "Element is not clickable" in result["error"]


# ── Type ref tests ───────────────────────────────────────────────────


class TestTypeRef:
    @pytest.mark.asyncio
    async def test_type_ref_success(self, tool, mock_page):
        """Type ref fills and types text into element."""
        mock_page.evaluate.return_value = {
            "selector": "#email-input",
            "tagName": "input",
            "description": "input Email",
        }

        result = await tool._type_ref(mock_page, {"ref": 1, "text": "test@example.com"})

        assert result["success"] is True
        assert result["ref"] == 1
        assert result["typed"] == "input Email"

        mock_page.locator.assert_called_once_with("#email-input")
        locator_first = mock_page.locator.return_value.first
        locator_first.scroll_into_view_if_needed.assert_called_once()
        # Verify fill("") to clear, then type with delay
        locator_first.fill.assert_called_once_with("")
        locator_first.type.assert_called_once_with("test@example.com", delay=50)

    @pytest.mark.asyncio
    async def test_type_ref_scroll_fails_continues(self, tool, mock_page):
        """Type ref continues if scroll fails."""
        mock_page.evaluate.return_value = {
            "selector": "#input",
            "tagName": "input",
            "description": "input Text",
        }
        locator_first = mock_page.locator.return_value.first
        locator_first.scroll_into_view_if_needed.side_effect = Exception("Scroll failed")

        result = await tool._type_ref(mock_page, {"ref": 2, "text": "hello"})

        assert result["success"] is True
        locator_first.fill.assert_called_once()
        locator_first.type.assert_called_once()

    @pytest.mark.asyncio
    async def test_type_ref_missing_text(self, tool, mock_page):
        """Type ref returns error when text param is missing."""
        result = await tool._type_ref(mock_page, {"ref": 1})

        assert result["success"] is False
        assert "Missing required parameter: text" in result["error"]

    @pytest.mark.asyncio
    async def test_type_ref_missing_ref(self, tool, mock_page):
        """Type ref returns error when ref param is missing."""
        result = await tool._type_ref(mock_page, {"text": "hello"})

        assert result["success"] is False
        assert "Missing required parameter: ref" in result["error"]

    @pytest.mark.asyncio
    async def test_type_ref_not_found(self, tool, mock_page):
        """Type ref returns error when ref doesn't exist."""
        mock_page.evaluate.return_value = None

        result = await tool._type_ref(mock_page, {"ref": 999, "text": "test"})

        assert result["success"] is False
        assert "Ref [999] not found" in result["error"]
        assert "Re-run snapshot" in result["error"]

    @pytest.mark.asyncio
    async def test_type_ref_type_fails(self, tool, mock_page):
        """Type ref returns error when typing fails."""
        mock_page.evaluate.return_value = {
            "selector": "#readonly",
            "tagName": "input",
            "description": "input Readonly",
        }
        locator_first = mock_page.locator.return_value.first
        locator_first.type.side_effect = Exception("Element is readonly")

        result = await tool._type_ref(mock_page, {"ref": 3, "text": "test"})

        assert result["success"] is False
        assert "Type into ref [3] failed" in result["error"]
        assert "Element is readonly" in result["error"]


# ── Select ref tests ─────────────────────────────────────────────────


class TestSelectRef:
    @pytest.mark.asyncio
    async def test_select_ref_success(self, tool, mock_page):
        """Select ref selects option in dropdown."""
        mock_page.evaluate.return_value = {
            "selector": "#country-select",
            "tagName": "select",
            "description": "select Country",
        }

        result = await tool._select_ref(mock_page, {"ref": 5, "value": "US"})

        assert result["success"] is True
        assert result["ref"] == 5
        assert result["selected"] == "US"

        mock_page.locator.assert_called_once_with("#country-select")
        locator_first = mock_page.locator.return_value.first
        locator_first.select_option.assert_called_once_with(value="US", timeout=10_000)

    @pytest.mark.asyncio
    async def test_select_ref_missing_value(self, tool, mock_page):
        """Select ref returns error when value param is missing."""
        result = await tool._select_ref(mock_page, {"ref": 1})

        assert result["success"] is False
        assert "Missing required parameter: value" in result["error"]

    @pytest.mark.asyncio
    async def test_select_ref_missing_ref(self, tool, mock_page):
        """Select ref returns error when ref param is missing."""
        result = await tool._select_ref(mock_page, {"value": "option1"})

        assert result["success"] is False
        assert "Missing required parameter: ref" in result["error"]

    @pytest.mark.asyncio
    async def test_select_ref_not_found(self, tool, mock_page):
        """Select ref returns error when ref doesn't exist."""
        mock_page.evaluate.return_value = None

        result = await tool._select_ref(mock_page, {"ref": 999, "value": "test"})

        assert result["success"] is False
        assert "Ref [999] not found" in result["error"]
        assert "Re-run snapshot" in result["error"]

    @pytest.mark.asyncio
    async def test_select_ref_select_fails(self, tool, mock_page):
        """Select ref returns error when selection fails."""
        mock_page.evaluate.return_value = {
            "selector": "#select",
            "tagName": "select",
            "description": "select Options",
        }
        locator_first = mock_page.locator.return_value.first
        locator_first.select_option.side_effect = Exception("Option not found")

        result = await tool._select_ref(mock_page, {"ref": 2, "value": "invalid"})

        assert result["success"] is False
        assert "Select ref [2] failed" in result["error"]
        assert "Option not found" in result["error"]


# ── Login action tests ───────────────────────────────────────────────


class TestLoginAction:
    @pytest.mark.asyncio
    async def test_login_action_success(self, tool, mock_page):
        """Login action calls LoginFlowManager.start_login_flow."""
        mock_manager = AsyncMock()
        mock_manager.start_login_flow.return_value = {
            "success": True,
            "message": "Login flow started",
        }
        tool._login_flow_manager = mock_manager
        tool._active_profile = "gmail"

        result = await tool._login(mock_page, {"url": "https://gmail.com"})

        assert result["success"] is True
        assert result["message"] == "Login flow started"
        mock_manager.start_login_flow.assert_called_once_with(
            profile="gmail",
            url="https://gmail.com",
            interval_ms=1500,
        )

    @pytest.mark.asyncio
    async def test_login_action_with_custom_interval(self, tool, mock_page):
        """Login action passes custom interval_ms."""
        mock_manager = AsyncMock()
        mock_manager.start_login_flow.return_value = {"success": True}
        tool._login_flow_manager = mock_manager
        tool._active_profile = "work"

        result = await tool._login(mock_page, {
            "url": "https://example.com/login",
            "interval_ms": 2000,
        })

        mock_manager.start_login_flow.assert_called_once_with(
            profile="work",
            url="https://example.com/login",
            interval_ms=2000,
        )

    @pytest.mark.asyncio
    async def test_login_action_default_profile(self, tool, mock_page):
        """Login action uses 'default' profile when none is active."""
        mock_manager = AsyncMock()
        mock_manager.start_login_flow.return_value = {"success": True}
        tool._login_flow_manager = mock_manager
        tool._active_profile = None

        result = await tool._login(mock_page, {"url": "https://site.com"})

        mock_manager.start_login_flow.assert_called_once()
        call_args = mock_manager.start_login_flow.call_args
        assert call_args.kwargs["profile"] == "default"

    @pytest.mark.asyncio
    async def test_login_action_no_manager(self, tool, mock_page):
        """Login action returns error when manager not configured."""
        tool._login_flow_manager = None

        result = await tool._login(mock_page, {"url": "https://example.com"})

        assert result["success"] is False
        assert "Login flow manager not configured" in result["error"]

    @pytest.mark.asyncio
    async def test_login_action_missing_url(self, tool, mock_page):
        """Login action returns error when url param is missing."""
        mock_manager = AsyncMock()
        tool._login_flow_manager = mock_manager

        result = await tool._login(mock_page, {})

        assert result["success"] is False
        assert "Missing required parameter: url" in result["error"]


# ── Set login flow manager tests ─────────────────────────────────────


class TestSetLoginFlowManager:
    def test_set_login_flow_manager(self, tool):
        """set_login_flow_manager wires manager and adds login action."""
        mock_manager = MagicMock()

        # Before: no login action
        assert "login" not in tool._action_dispatch
        assert tool._login_flow_manager is None

        tool.set_login_flow_manager(mock_manager)

        # After: login action registered
        assert tool._login_flow_manager is mock_manager
        assert "login" in tool._action_dispatch
        assert tool._action_dispatch["login"] == tool._login

    def test_set_login_flow_manager_multiple_times(self, tool):
        """set_login_flow_manager can be called multiple times."""
        manager1 = MagicMock()
        manager2 = MagicMock()

        tool.set_login_flow_manager(manager1)
        assert tool._login_flow_manager is manager1

        tool.set_login_flow_manager(manager2)
        assert tool._login_flow_manager is manager2
        # Login action still registered
        assert "login" in tool._action_dispatch
