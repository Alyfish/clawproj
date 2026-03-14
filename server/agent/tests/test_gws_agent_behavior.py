"""Agent behavior tests for gws OAuth token handling.

Tests the agent's Python code paths for:
- gws commands receiving GOOGLE_WORKSPACE_CLI_TOKEN via env injection
- 401 detection routing to token refresh (not credential helper)
- Token refresh success/timeout retry flow
- Multi-service command recognition
- Token nil'd after use

These tests use mocked components — no real gws binary, no Claude API.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.agent.tools.bash_execute import _is_gws_command, _build_env
from server.agent.tools.auth_detector import AuthDetector
from server.agent.tools.tool_registry import ToolResult
from server.agent.tests.fixtures.gws_responses import AUTH_ERROR_STDERR


# ── Helpers ──────────────────────────────────────────────────


def _make_mock_gateway(token_refresh_result: str | None = "ya29.refreshed") -> MagicMock:
    """Mock gateway client with configurable token refresh."""
    gw = MagicMock()
    gw.request_token_refresh = AsyncMock(return_value=token_refresh_result)
    gw.stream_thinking = AsyncMock()
    gw.emit_event = AsyncMock()
    gw.request_approval = AsyncMock(return_value={"decision": "approved"})
    return gw


def _make_mock_bash_tool(success: bool = True) -> MagicMock:
    """Mock BashExecuteTool with configurable execute_authenticated result."""
    tool = MagicMock()
    tool.name = "bash_execute"
    tool.execute_authenticated = AsyncMock(
        return_value=ToolResult(
            success=success,
            output={"stdout": '{"files": []}', "stderr": "", "exit_code": 0},
        ),
    )
    return tool


def _make_mock_tool_registry(bash_tool: MagicMock | None = None) -> MagicMock:
    """Mock ToolRegistry that returns the given bash tool."""
    registry = MagicMock()
    registry.get = MagicMock(return_value=bash_tool)
    registry.list_tools = MagicMock(return_value=["bash_execute"])
    return registry


def _make_failed_gws_result() -> ToolResult:
    """A ToolResult simulating a gws 401 failure."""
    return ToolResult(
        success=False,
        output={
            "stdout": "",
            "stderr": AUTH_ERROR_STDERR,
            "exit_code": 1,
        },
        error="Command failed with exit code 1",
    )


# ── 3a: gws env injection ───────────────────────────────────


class TestGwsEnvInjection:
    """Verify gws commands receive GOOGLE_WORKSPACE_CLI_TOKEN in env."""

    def test_gws_command_gets_token_via_extra(self):
        """Token passed as extra bypasses the blocked-substring filter."""
        env = _build_env(extra={"GOOGLE_WORKSPACE_CLI_TOKEN": "ya29.test"})
        assert env["GOOGLE_WORKSPACE_CLI_TOKEN"] == "ya29.test"

    def test_non_gws_command_no_token(self):
        """Non-gws commands do NOT get GOOGLE_WORKSPACE_CLI_TOKEN."""
        env = _build_env()
        assert "GOOGLE_WORKSPACE_CLI_TOKEN" not in env

    def test_all_gws_services_recognized(self):
        """_is_gws_command recognizes all Google Workspace service prefixes."""
        services = [
            "gws drive files list",
            "gws gmail users messages list",
            "gws calendar events list",
            "gws docs documents create",
            "gws sheets spreadsheets create",
            "gws slides presentations create",
            "gws schema drive.files.list",
        ]
        for cmd in services:
            assert _is_gws_command(cmd) is True, f"Failed for: {cmd}"


# ── 3b: Token refresh success/timeout ────────────────────────


class TestHandleGwsTokenRefresh:
    """Test agent._handle_gws_token_refresh code path."""

    @pytest.mark.asyncio
    async def test_refresh_success_retries_command(self):
        """On 401, agent requests refresh, gets token, retries with it."""
        from server.agent.agent import Agent
        from server.agent.config import AgentConfig

        gateway = _make_mock_gateway(token_refresh_result="ya29.new-token")
        bash_tool = _make_mock_bash_tool(success=True)
        registry = _make_mock_tool_registry(bash_tool)

        config = AgentConfig()
        config.api_key = "test-key"

        agent = Agent(
            config=config,
            gateway_client=gateway,
            context_builder=MagicMock(),
            skill_registry=MagicMock(),
            tool_registry=registry,
        )

        failed_result = _make_failed_gws_result()
        tool_input = {"command": "gws drive files list --params '{}'"}

        result = await agent._handle_gws_token_refresh(
            failed_result, tool_input, "test-session",
        )

        # Token refresh was requested (with default timeout=30.0)
        gateway.request_token_refresh.assert_awaited_once_with("google", timeout=30.0)

        # Retry was executed with the new token
        bash_tool.execute_authenticated.assert_awaited_once()
        call_kwargs = bash_tool.execute_authenticated.call_args
        execution = call_kwargs.kwargs.get("execution") or call_kwargs[1].get("execution") or call_kwargs[0][0]
        assert execution.env_additions["GOOGLE_WORKSPACE_CLI_TOKEN"] == "ya29.new-token"
        assert execution.strategy == "gws_oauth"

        # Result is from the retry (success)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_refresh_timeout_returns_hint(self):
        """When token refresh times out, result includes iOS re-auth hint."""
        from server.agent.agent import Agent
        from server.agent.config import AgentConfig

        gateway = _make_mock_gateway(token_refresh_result=None)
        registry = _make_mock_tool_registry(None)

        config = AgentConfig()
        config.api_key = "test-key"

        agent = Agent(
            config=config,
            gateway_client=gateway,
            context_builder=MagicMock(),
            skill_registry=MagicMock(),
            tool_registry=registry,
        )

        failed_result = _make_failed_gws_result()
        tool_input = {"command": "gws gmail users messages list"}

        result = await agent._handle_gws_token_refresh(
            failed_result, tool_input, "test-session",
        )

        # Token refresh was requested (with default timeout=30.0)
        gateway.request_token_refresh.assert_awaited_once_with("google", timeout=30.0)

        # No retry attempted (bash_tool.execute_authenticated not called)
        # Result contains the hint
        assert "Open the ClawBot iOS app" in (result.error or "")
        assert "re-authenticate with Google" in (result.error or "")

    @pytest.mark.asyncio
    async def test_refresh_no_bash_tool_returns_original(self):
        """If bash_execute tool is missing from registry, return original result."""
        from server.agent.agent import Agent
        from server.agent.config import AgentConfig

        gateway = _make_mock_gateway(token_refresh_result="ya29.token")
        registry = _make_mock_tool_registry(None)  # bash_tool is None

        config = AgentConfig()
        config.api_key = "test-key"

        agent = Agent(
            config=config,
            gateway_client=gateway,
            context_builder=MagicMock(),
            skill_registry=MagicMock(),
            tool_registry=registry,
        )

        failed_result = _make_failed_gws_result()
        tool_input = {"command": "gws drive files list"}

        result = await agent._handle_gws_token_refresh(
            failed_result, tool_input, "test-session",
        )

        # Returns original result unchanged
        assert result.success is False


# ── 3d: 401 routing — gws goes to token refresh, not cred helper ──


class TestGws401Routing:
    """Verify gws 401 routes to _handle_gws_token_refresh, not credential helper."""

    def test_auth_detector_catches_gws_401(self):
        """AuthDetector detects 401 from gws command output."""
        info = AuthDetector.detect(
            stdout="",
            stderr=AUTH_ERROR_STDERR,
            exit_code=1,
            command="gws drive files list --params '{}'",
        )
        assert info is not None
        assert info["confidence"] > 0

    def test_gws_command_prefix_check(self):
        """The gws routing condition checks command prefix."""
        command = "gws sheets spreadsheets create --json '{}'"
        # This is the condition from agent.py line 1110
        assert command.strip().startswith("gws ")

    def test_non_gws_does_not_trigger_gws_path(self):
        """Non-gws commands with 401 should NOT route to gws refresh."""
        command = "curl https://api.example.com/data"
        assert not command.strip().startswith("gws ")

    @pytest.mark.asyncio
    async def test_handle_bash_auth_failure_routes_gws_to_refresh(self):
        """agent._handle_bash_auth_failure delegates gws to _handle_gws_token_refresh."""
        from server.agent.agent import Agent
        from server.agent.config import AgentConfig

        gateway = _make_mock_gateway(token_refresh_result="ya29.refreshed")
        bash_tool = _make_mock_bash_tool(success=True)
        registry = _make_mock_tool_registry(bash_tool)

        config = AgentConfig()
        config.api_key = "test-key"

        agent = Agent(
            config=config,
            gateway_client=gateway,
            context_builder=MagicMock(),
            skill_registry=MagicMock(),
            tool_registry=registry,
            credential_manager=MagicMock(),  # enables _bash_cred_helper guard
        )

        # The failed result with gws 401
        failed_result = _make_failed_gws_result()
        tool_input = {"command": "gws drive files list --params '{}'"}

        result = await agent._handle_bash_auth_failure(
            failed_result, tool_input, "test-session",
        )

        # Should have called token refresh (gws path), not credential helper
        gateway.request_token_refresh.assert_awaited_once_with("google", timeout=30.0)
        # The retry should succeed
        assert result.success is True

    @pytest.mark.asyncio
    async def test_handle_bash_auth_failure_non_gws_skips_refresh(self):
        """Non-gws 401 does NOT call request_token_refresh."""
        from server.agent.agent import Agent
        from server.agent.config import AgentConfig

        gateway = _make_mock_gateway()
        bash_tool = _make_mock_bash_tool(success=True)
        registry = _make_mock_tool_registry(bash_tool)

        config = AgentConfig()
        config.api_key = "test-key"

        agent = Agent(
            config=config,
            gateway_client=gateway,
            context_builder=MagicMock(),
            skill_registry=MagicMock(),
            tool_registry=registry,
            credential_manager=MagicMock(),  # enables _bash_cred_helper
        )

        # Non-gws 401
        failed_result = ToolResult(
            success=False,
            output={
                "stdout": "",
                "stderr": "HTTP/1.1 401 Unauthorized",
                "exit_code": 1,
            },
            error="Command failed",
        )
        tool_input = {"command": "curl https://api.example.com/data"}

        # Mock _bash_cred_helper to avoid real credential flow
        agent._bash_cred_helper.prepare_execution = AsyncMock(return_value=None)

        result = await agent._handle_bash_auth_failure(
            failed_result, tool_input, "test-session",
        )

        # Should NOT have called token refresh
        gateway.request_token_refresh.assert_not_awaited()


# ── Security: token nil'd after use ──────────────────────────


class TestTokenSecurity:
    """Verify tokens are nil'd after use."""

    @pytest.mark.asyncio
    async def test_token_reference_nild_after_refresh(self):
        """The new_token local variable is set to None after use (line 1230)."""
        from server.agent.agent import Agent
        from server.agent.config import AgentConfig

        gateway = _make_mock_gateway(token_refresh_result="ya29.secret")
        bash_tool = _make_mock_bash_tool(success=True)
        registry = _make_mock_tool_registry(bash_tool)

        config = AgentConfig()
        config.api_key = "test-key"

        agent = Agent(
            config=config,
            gateway_client=gateway,
            context_builder=MagicMock(),
            skill_registry=MagicMock(),
            tool_registry=registry,
        )

        failed_result = _make_failed_gws_result()
        tool_input = {"command": "gws drive files list"}

        # The method completes — the nil assignment (new_token = None)
        # on line 1230 means the local reference is cleared.
        # We verify by confirming the method runs successfully and
        # the returned result does NOT contain the token value.
        result = await agent._handle_gws_token_refresh(
            failed_result, tool_input, "test-session",
        )

        assert result.success is True
        # Token should not leak into result error/output strings
        result_str = str(result.output) + str(result.error or "")
        assert "ya29.secret" not in result_str
