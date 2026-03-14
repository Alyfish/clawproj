"""
Tests for Google OAuth token handling in bash_execute and auth_detector.

Covers:
- _is_gws_command detection
- gws commands get GOOGLE_WORKSPACE_CLI_TOKEN env var via extra
- Non-gws commands do NOT get the token
- AuthDetector recognizes gws as a tool type
"""
from __future__ import annotations

import os

import pytest

from server.agent.tools.bash_execute import _is_gws_command, _build_env
from server.agent.tools.auth_detector import AuthDetector


# ── _is_gws_command ──────────────────────────────────────────


class TestIsGwsCommand:
    def test_gws_with_args(self):
        assert _is_gws_command("gws gmail users messages list") is True

    def test_gws_alone(self):
        assert _is_gws_command("gws") is True

    def test_gws_with_leading_space(self):
        assert _is_gws_command("  gws drive files list") is True

    def test_not_gws(self):
        assert _is_gws_command("curl https://example.com") is False

    def test_gws_in_middle(self):
        assert _is_gws_command("echo gws") is False

    def test_empty_string(self):
        assert _is_gws_command("") is False

    def test_gws_prefix_not_command(self):
        assert _is_gws_command("gwsomething else") is False


# ── gws env injection ───────────────────────────────────────


class TestGwsEnvInjection:
    def test_gws_token_in_env_via_extra(self):
        """Token passed via extra bypasses the TOKEN blocker."""
        env = _build_env(extra={"GOOGLE_WORKSPACE_CLI_TOKEN": "test123"})
        assert env["GOOGLE_WORKSPACE_CLI_TOKEN"] == "test123"

    def test_token_not_in_default_env(self):
        """Token in os.environ is NOT passed through default _build_env."""
        os.environ["GOOGLE_WORKSPACE_CLI_TOKEN"] = "should-not-appear"
        try:
            env = _build_env()
            assert "GOOGLE_WORKSPACE_CLI_TOKEN" not in env
        finally:
            os.environ.pop("GOOGLE_WORKSPACE_CLI_TOKEN", None)


# ── AuthDetector gws recognition ─────────────────────────────


class TestAuthDetectorGws:
    def test_gws_recognized_as_tool(self):
        """gws commands are recognized by _tool_from_command."""
        assert AuthDetector._tool_from_command("gws gmail list") == "gws"

    def test_gws_401_detected(self):
        """gws 401 output is detected as auth failure."""
        info = AuthDetector.detect(
            stdout="",
            stderr="Error: 401 Unauthorized - Request had invalid authentication credentials.",
            exit_code=1,
            command="gws gmail users messages list --params '{}'",
        )
        assert info is not None
        # Pattern matches as "http" (401 Unauthorized), tool upgrade only
        # applies to "generic" matches. The agent's _handle_bash_auth_failure
        # uses command.startswith("gws ") as the primary gws check.
        assert info["tool"] in ("http", "gws")

    def test_gws_success_not_detected(self):
        """Successful gws commands are not detected as auth failures."""
        info = AuthDetector.detect(
            stdout='{"messages": []}',
            stderr="",
            exit_code=0,
            command="gws gmail users messages list",
        )
        assert info is None

    def test_non_gws_not_tagged_gws(self):
        """Non-gws commands with 401 don't get tool=gws."""
        info = AuthDetector.detect(
            stdout="",
            stderr="HTTP/1.1 401 Unauthorized",
            exit_code=1,
            command="curl https://api.example.com/data",
        )
        assert info is not None
        assert info["tool"] == "http"
