"""
Integration tests for bash credential injection pipeline.

Wires REAL AuthDetector + BashCredentialHelper + BashExecuteTool together.
Only CredentialManager.request_credentials() is mocked (requires iOS).
Subprocess is mocked via asyncio.create_subprocess_shell patch.

Tests the full chain:
  bash command fails → AuthDetector detects auth failure →
  BashCredentialHelper builds injection strategy →
  BashExecuteTool retries with credentials → cleanup
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.agent.tools.auth_detector import AuthDetector
from server.agent.tools.bash_credential_helper import (
    BashCredentialHelper,
)
from server.agent.tools.bash_execute import BashExecuteTool
from server.agent.tools.tool_registry import ToolResult


# ── Fixtures ────────────────────────────────────────────────────


_TEST_CREDS = [{"username": "testuser", "password": "testpass"}]


def _mock_cred_manager(
    credentials: list[dict[str, str]] | None = None,
) -> AsyncMock:
    cm = AsyncMock()
    cm.request_credentials = AsyncMock(
        return_value=credentials if credentials is not None else _TEST_CREDS
    )
    return cm


@pytest.fixture
def cred_manager():
    return _mock_cred_manager()


@pytest.fixture
def helper(cred_manager):
    return BashCredentialHelper(credential_manager=cred_manager)


@pytest.fixture
def bash_tool(helper):
    tool = BashExecuteTool()
    tool.set_bash_credential_helper(helper)
    return tool


def _mock_process(stdout: bytes, stderr: bytes, returncode: int):
    """Create a mock subprocess with given outputs."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = AsyncMock()
    proc.wait = AsyncMock()
    return proc


# ── Integration: Explicit authenticate param ───────────────────


class TestExplicitAuthentication:
    @pytest.mark.asyncio
    async def test_authenticate_param_injects_netrc(self, bash_tool):
        """execute(authenticate={...}) injects credentials on first call."""
        proc = _mock_process(
            b'{"data": "secret_api_response"}', b"", 0
        )
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            result = await bash_tool.execute(
                command="curl -s https://api.example.com/data",
                authenticate={
                    "domain": "api.example.com",
                    "tool_hint": "curl",
                    "reason": "Fetch private data",
                },
            )
        assert result.success
        assert "secret_api_response" in result.output["stdout"]

    @pytest.mark.asyncio
    async def test_authenticate_git_injects_askpass(self, bash_tool):
        """Git commands get GIT_ASKPASS env var injection."""
        proc = _mock_process(b"Cloning into 'repo'...\n", b"", 0)
        with patch("asyncio.create_subprocess_shell", return_value=proc) as mock_sub:
            result = await bash_tool.execute(
                command="git clone https://github.com/org/private.git",
                authenticate={
                    "domain": "github.com",
                    "tool_hint": "git",
                    "reason": "Clone private repo",
                },
            )
        assert result.success
        # Verify GIT_ASKPASS was in the env passed to subprocess
        call_kwargs = mock_sub.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env", {})
        assert "GIT_ASKPASS" in env
        assert "GIT_TERMINAL_PROMPT" in env
        assert env["GIT_TERMINAL_PROMPT"] == "0"


# ── Integration: Auth detection → retry chain ──────────────────


class TestAuthDetectionRetry:
    @pytest.mark.asyncio
    async def test_curl_401_detected_by_auth_detector(self):
        """AuthDetector correctly identifies curl 401 with high confidence."""
        info = AuthDetector.detect(
            stdout="",
            stderr="HTTP/1.1 401 Unauthorized\n",
            exit_code=22,
            command="curl -s https://api.example.com/data",
        )
        assert info is not None
        assert info["detected"]
        assert info["confidence"] >= 0.8
        assert info["domain"] == "api.example.com"

    @pytest.mark.asyncio
    async def test_git_auth_failure_detected(self):
        """AuthDetector identifies git authentication failure."""
        info = AuthDetector.detect(
            stdout="",
            stderr="fatal: Authentication failed for 'https://github.com/user/repo.git'",
            exit_code=128,
            command="git clone https://github.com/user/repo.git",
        )
        assert info is not None
        assert info["tool"] == "git"
        assert info["confidence"] >= 0.9
        assert info["domain"] == "github.com"

    @pytest.mark.asyncio
    async def test_detect_then_prepare_then_execute(self, helper):
        """Full chain: detect → prepare → execute_authenticated."""
        # Step 1: Detect
        info = AuthDetector.detect(
            stdout="",
            stderr="HTTP/1.1 401 Unauthorized",
            exit_code=22,
            command="curl -s https://api.example.com/data",
        )
        assert info is not None
        assert info["confidence"] >= 0.8

        # Step 2: Prepare
        execution = await helper.prepare_execution(
            domain=info["domain"],
            tool_hint=info["tool"],
            command="curl -s https://api.example.com/data",
            reason=f"Auth failed: {info['pattern']}",
        )
        assert execution is not None
        assert execution.strategy == "netrc"
        assert "--netrc-file" in execution.modified_command

        # Step 3: Execute authenticated
        tool = BashExecuteTool()
        proc = _mock_process(b'{"ok": true}', b"", 0)
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            retry_result = await tool.execute_authenticated(execution)

        assert retry_result.success

        # Step 4: Cleanup
        BashCredentialHelper.cleanup(execution)
        for p in execution.cleanup_paths:
            assert not p.exists()


# ── Integration: Cleanup guarantees ────────────────────────────


class TestCleanupGuarantees:
    @pytest.mark.asyncio
    async def test_cleanup_runs_after_authenticated_execute(self, bash_tool):
        """Temp files are cleaned up even when execute() succeeds."""
        # Snapshot existing files before test
        before = set(Path("/tmp").glob(".clawbot-netrc-*"))

        proc = _mock_process(b"ok", b"", 0)
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            await bash_tool.execute(
                command="curl https://api.example.com",
                authenticate={
                    "domain": "api.example.com",
                    "tool_hint": "curl",
                },
            )

        # No NEW temp files should remain after execute()
        after = set(Path("/tmp").glob(".clawbot-netrc-*"))
        new_files = after - before
        assert len(new_files) == 0, f"New stale temp files: {new_files}"

    @pytest.mark.asyncio
    async def test_cleanup_runs_on_subprocess_failure(self, bash_tool):
        """Temp files cleaned up even when subprocess raises."""
        before = set(Path("/tmp").glob(".clawbot-netrc-*"))

        with patch(
            "asyncio.create_subprocess_shell",
            side_effect=OSError("spawn failed"),
        ):
            result = await bash_tool.execute(
                command="curl https://api.example.com",
                authenticate={
                    "domain": "api.example.com",
                    "tool_hint": "curl",
                },
            )
        assert not result.success
        after = set(Path("/tmp").glob(".clawbot-netrc-*"))
        new_files = after - before
        assert len(new_files) == 0, f"New stale temp files: {new_files}"

    @pytest.mark.asyncio
    async def test_failed_retry_records_domain(self, helper, cred_manager):
        """record_credential_failure() called after retry also fails."""
        # Simulate: detect auth failure → prepare → retry fails
        execution = await helper.prepare_execution(
            domain="api.example.com",
            tool_hint="curl",
            command="curl https://api.example.com",
            reason="Auth failed",
        )
        assert execution is not None

        tool = BashExecuteTool()
        proc = _mock_process(b"", b"Still 401", 22)
        with patch("asyncio.create_subprocess_shell", return_value=proc):
            retry_result = await tool.execute_authenticated(execution)

        assert not retry_result.success

        # Record failure
        helper.record_credential_failure("api.example.com")
        assert "api.example.com" in helper._failed_domains

        # Subsequent prepare should return None (domain is failed)
        second = await helper.prepare_execution(
            domain="api.example.com",
            tool_hint="curl",
            command="curl https://api.example.com",
        )
        assert second is None

        BashCredentialHelper.cleanup(execution)


# ── Integration: Confidence gating ─────────────────────────────


class TestConfidenceGating:
    def test_low_confidence_no_retry(self):
        """Generic 'Access denied' has confidence < 0.8 → should not trigger retry."""
        info = AuthDetector.detect(
            stdout="",
            stderr="Access denied",
            exit_code=1,
            command="some-cli --flag",
        )
        # Access denied is generic, confidence 0.5
        assert info is not None
        assert info["confidence"] < 0.8

    def test_no_domain_extractable(self):
        """Auth failure detected but no domain in command → can't request creds."""
        info = AuthDetector.detect(
            stdout="",
            stderr="HTTP/1.1 401 Unauthorized",
            exit_code=1,
            command="./local-script.sh",
        )
        assert info is not None
        assert info["domain"] is None


# ── Integration: Security ──────────────────────────────────────


class TestCredentialSecurity:
    @pytest.mark.asyncio
    async def test_credentials_never_in_command_args_curl(self, helper):
        """Curl: credentials go to netrc file, not command string."""
        execution = await helper.prepare_execution(
            "example.com", "curl", "curl https://example.com"
        )
        assert execution is not None
        assert "testuser" not in execution.modified_command
        assert "testpass" not in execution.modified_command
        BashCredentialHelper.cleanup(execution)

    @pytest.mark.asyncio
    async def test_credentials_never_in_command_args_git(self, helper):
        """Git: credentials go to env vars, not command string."""
        execution = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert execution is not None
        assert "testuser" not in execution.modified_command
        assert "testpass" not in execution.modified_command
        BashCredentialHelper.cleanup(execution)

    @pytest.mark.asyncio
    async def test_credentials_never_in_command_args_docker(self, helper):
        """Docker: password piped via stdin, not in command string."""
        execution = await helper.prepare_execution(
            "ghcr.io", "docker", "docker pull ghcr.io/org/img"
        )
        assert execution is not None
        assert "testpass" not in execution.modified_command
        BashCredentialHelper.cleanup(execution)

    @pytest.mark.asyncio
    async def test_git_askpass_script_no_literal_creds(self, helper):
        """GIT_ASKPASS script references env vars, not literal credentials."""
        execution = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert execution is not None
        assert len(execution.setup_files) == 1

        script_content = execution.setup_files[0].read_text()
        assert "testuser" not in script_content
        assert "testpass" not in script_content
        assert "$_CLAWBOT_GIT_USER" in script_content
        assert "$_CLAWBOT_GIT_PASS" in script_content
        BashCredentialHelper.cleanup(execution)

    @pytest.mark.asyncio
    async def test_env_vars_bypass_blocked_filter(self, bash_tool):
        """GIT_ASKPASS env var is NOT blocked by _BLOCKED_ENV_SUBSTRINGS."""
        proc = _mock_process(b"ok", b"", 0)
        with patch("asyncio.create_subprocess_shell", return_value=proc) as mock_sub:
            await bash_tool.execute(
                command="git clone https://github.com/org/repo.git",
                authenticate={
                    "domain": "github.com",
                    "tool_hint": "git",
                },
            )
        call_kwargs = mock_sub.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env", {})
        # GIT_ASKPASS should pass through even though env filter exists
        assert "GIT_ASKPASS" in env
        # _CLAWBOT_GIT_USER/_CLAWBOT_GIT_PASS are credential-adjacent but
        # intentionally bypass the filter via _build_env(extra=...)
        assert "_CLAWBOT_GIT_USER" in env
        assert "_CLAWBOT_GIT_PASS" in env
