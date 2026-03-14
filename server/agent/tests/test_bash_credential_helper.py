"""
Tests for BashCredentialHelper — secure credential injection for CLI tools.

Covers:
- Strategy selection per tool_hint (netrc, git_credential, gh_token, etc.)
- Netrc file creation (content, permissions, flag insertion)
- Git credential helper script (content, permissions, env vars)
- GH token via env var + caching
- Docker stdin pipe
- Generic env vars
- Token cache (get/set/expiry)
- Cleanup removes temp files
- No credentials in command arguments
- None/empty credential handling
- set_credential_manager wiring
"""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from server.agent.tools.bash_credential_helper import (
    AuthenticatedExecution,
    BashCredentialHelper,
)


# ── Fixtures ────────────────────────────────────────────────────


def _mock_cred_manager(
    credentials: list[dict[str, str]] | None = None,
) -> AsyncMock:
    """Create a mock CredentialManager with preset return value."""
    cm = AsyncMock()
    cm.request_credentials = AsyncMock(return_value=credentials)
    return cm


_DEFAULT_CREDS = [{"username": "user@test.com", "password": "s3cret"}]


@pytest.fixture
def helper():
    """BashCredentialHelper with mocked credential_manager returning creds."""
    cm = _mock_cred_manager(_DEFAULT_CREDS)
    return BashCredentialHelper(credential_manager=cm)


@pytest.fixture
def helper_no_creds():
    """BashCredentialHelper with credential_manager returning None."""
    cm = _mock_cred_manager(None)
    return BashCredentialHelper(credential_manager=cm)


# ── Strategy Selection ──────────────────────────────────────────


class TestStrategySelection:
    @pytest.mark.asyncio
    async def test_curl_uses_netrc(self, helper):
        result = await helper.prepare_execution(
            "example.com", "curl", "curl https://example.com/api"
        )
        assert result is not None
        assert result.strategy == "netrc"

    @pytest.mark.asyncio
    async def test_wget_uses_netrc(self, helper):
        result = await helper.prepare_execution(
            "example.com", "wget", "wget https://example.com/file"
        )
        assert result is not None
        assert result.strategy == "netrc"
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_git_uses_git_credential(self, helper):
        result = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert result is not None
        assert result.strategy == "git_credential"
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_gh_uses_gh_token(self, helper):
        result = await helper.prepare_execution(
            "github.com", "gh", "gh pr list"
        )
        assert result is not None
        assert result.strategy == "gh_token"

    @pytest.mark.asyncio
    async def test_docker_uses_docker_stdin(self, helper):
        result = await helper.prepare_execution(
            "ghcr.io", "docker", "docker pull ghcr.io/org/img:latest"
        )
        assert result is not None
        assert result.strategy == "docker_stdin"

    @pytest.mark.asyncio
    async def test_unknown_tool_uses_env(self, helper):
        result = await helper.prepare_execution(
            "example.com", "unknown_tool", "some-cli --flag"
        )
        assert result is not None
        assert result.strategy == "env"


# ── Netrc Strategy ──────────────────────────────────────────────


class TestNetrcStrategy:
    @pytest.mark.asyncio
    async def test_netrc_file_created_with_correct_content(self, helper):
        result = await helper.prepare_execution(
            "api.example.com", "curl", "curl https://api.example.com/data"
        )
        assert result is not None
        assert len(result.setup_files) == 1

        netrc_path = result.setup_files[0]
        assert netrc_path.exists()
        content = netrc_path.read_text()
        assert "machine api.example.com" in content
        assert "login user@test.com" in content
        assert "password s3cret" in content
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_netrc_file_has_0600_permissions(self, helper):
        result = await helper.prepare_execution(
            "example.com", "curl", "curl https://example.com"
        )
        assert result is not None
        netrc_path = result.setup_files[0]
        mode = netrc_path.stat().st_mode
        assert mode & stat.S_IRUSR != 0  # owner read
        assert mode & stat.S_IWUSR != 0  # owner write
        assert mode & stat.S_IRWXG == 0  # no group
        assert mode & stat.S_IRWXO == 0  # no other
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_netrc_flag_inserted_after_curl(self, helper):
        result = await helper.prepare_execution(
            "example.com", "curl", "curl -sL https://example.com/api"
        )
        assert result is not None
        assert "--netrc-file" in result.modified_command
        assert result.modified_command.startswith("curl --netrc-file")
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_netrc_flag_inserted_after_wget(self, helper):
        result = await helper.prepare_execution(
            "example.com", "wget", "wget -q https://example.com/file"
        )
        assert result is not None
        assert "--netrc-file" in result.modified_command
        assert "wget --netrc-file" in result.modified_command
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_netrc_cleanup_deletes_file(self, helper):
        result = await helper.prepare_execution(
            "example.com", "curl", "curl https://example.com"
        )
        assert result is not None
        netrc_path = result.setup_files[0]
        assert netrc_path.exists()
        BashCredentialHelper.cleanup(result)
        assert not netrc_path.exists()


# ── Git Credential Strategy ─────────────────────────────────────


class TestGitCredentialStrategy:
    @pytest.mark.asyncio
    async def test_git_helper_script_created(self, helper):
        result = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert result is not None
        assert len(result.setup_files) == 1
        script_path = result.setup_files[0]
        assert script_path.exists()

        content = script_path.read_text()
        assert "#!/bin/sh" in content
        assert "$_CLAWBOT_GIT_USER" in content
        assert "$_CLAWBOT_GIT_PASS" in content
        # Script must NOT contain literal credentials
        assert "s3cret" not in content
        assert "user@test.com" not in content
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_git_helper_has_0700_permissions(self, helper):
        result = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert result is not None
        script_path = result.setup_files[0]
        mode = script_path.stat().st_mode
        assert mode & stat.S_IRWXU == stat.S_IRWXU  # owner rwx
        assert mode & stat.S_IRWXG == 0
        assert mode & stat.S_IRWXO == 0
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_git_askpass_env_set(self, helper):
        result = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert result is not None
        assert "GIT_ASKPASS" in result.env_additions
        assert result.env_additions["GIT_ASKPASS"] == str(result.setup_files[0])
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_git_terminal_prompt_disabled(self, helper):
        result = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert result is not None
        assert result.env_additions.get("GIT_TERMINAL_PROMPT") == "0"
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_git_creds_passed_via_env(self, helper):
        result = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert result is not None
        assert result.env_additions["_CLAWBOT_GIT_USER"] == "user@test.com"
        assert result.env_additions["_CLAWBOT_GIT_PASS"] == "s3cret"
        BashCredentialHelper.cleanup(result)


# ── GH Token Strategy ──────────────────────────────────────────


class TestGhTokenStrategy:
    @pytest.mark.asyncio
    async def test_gh_token_set_in_env(self, helper):
        result = await helper.prepare_execution(
            "github.com", "gh", "gh pr list"
        )
        assert result is not None
        assert result.env_additions == {"GH_TOKEN": "s3cret"}

    @pytest.mark.asyncio
    async def test_gh_token_cached_for_reuse(self, helper):
        result = await helper.prepare_execution(
            "github.com", "gh", "gh pr list"
        )
        assert result is not None
        # Token should be cached
        assert helper.get_cached_token("github.com") == "s3cret"

    @pytest.mark.asyncio
    async def test_gh_no_command_modification(self, helper):
        cmd = "gh pr list --repo org/repo"
        result = await helper.prepare_execution(
            "github.com", "gh", cmd
        )
        assert result is not None
        assert result.modified_command == cmd


# ── NPM Token Strategy ─────────────────────────────────────────


class TestNpmTokenStrategy:
    @pytest.mark.asyncio
    async def test_npm_token_set_in_env(self, helper):
        result = await helper.prepare_execution(
            "registry.npmjs.org", "npm", "npm install private-pkg"
        )
        assert result is not None
        assert result.env_additions == {"NPM_TOKEN": "s3cret"}

    @pytest.mark.asyncio
    async def test_npm_token_cached(self, helper):
        await helper.prepare_execution(
            "registry.npmjs.org", "npm", "npm install private-pkg"
        )
        assert helper.get_cached_token("registry.npmjs.org") == "s3cret"


# ── Docker Stdin Strategy ──────────────────────────────────────


class TestDockerStdinStrategy:
    @pytest.mark.asyncio
    async def test_docker_login_prepended(self, helper):
        result = await helper.prepare_execution(
            "ghcr.io", "docker", "docker pull ghcr.io/org/img:latest"
        )
        assert result is not None
        assert result.modified_command.startswith("docker login")
        assert "--password-stdin" in result.modified_command
        assert "ghcr.io" in result.modified_command
        assert "docker pull ghcr.io/org/img:latest" in result.modified_command

    @pytest.mark.asyncio
    async def test_docker_password_via_stdin(self, helper):
        result = await helper.prepare_execution(
            "ghcr.io", "docker", "docker pull ghcr.io/org/img:latest"
        )
        assert result is not None
        assert result.stdin_input == "s3cret"


# ── Generic Env Strategy ───────────────────────────────────────


class TestGenericEnvStrategy:
    @pytest.mark.asyncio
    async def test_clawbot_user_pass_in_env(self, helper):
        result = await helper.prepare_execution(
            "example.com", "generic", "some-cli --flag"
        )
        assert result is not None
        assert result.env_additions == {
            "CLAWBOT_USER": "user@test.com",
            "CLAWBOT_PASS": "s3cret",
        }

    @pytest.mark.asyncio
    async def test_generic_command_unchanged(self, helper):
        cmd = "some-cli --flag value"
        result = await helper.prepare_execution(
            "example.com", "generic", cmd
        )
        assert result is not None
        assert result.modified_command == cmd


# ── Token Cache ─────────────────────────────────────────────────


class TestTokenCache:
    def test_cache_token_and_retrieve(self, helper):
        helper.cache_token("github.com", "tok_123", ttl=3600.0)
        assert helper.get_cached_token("github.com") == "tok_123"

    def test_expired_token_returns_none(self, helper):
        helper._token_cache["github.com"] = {
            "token": "expired_tok",
            "expires_at": time.time() - 1,
        }
        assert helper.get_cached_token("github.com") is None
        # Should also evict the expired entry
        assert "github.com" not in helper._token_cache

    @pytest.mark.asyncio
    async def test_cached_token_bypasses_credential_request(self, helper):
        helper.cache_token("github.com", "cached_tok", ttl=3600.0)
        result = await helper.prepare_execution(
            "github.com", "gh", "gh pr list"
        )
        assert result is not None
        assert result.env_additions["GH_TOKEN"] == "cached_tok"
        # Credential manager should NOT have been called
        helper._credential_manager.request_credentials.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_triggers_credential_request(self, helper):
        result = await helper.prepare_execution(
            "github.com", "gh", "gh pr list"
        )
        assert result is not None
        helper._credential_manager.request_credentials.assert_called_once()

    def test_cache_miss_returns_none(self, helper):
        assert helper.get_cached_token("unknown.com") is None


# ── Security ────────────────────────────────────────────────────


class TestSecurity:
    @pytest.mark.asyncio
    async def test_no_creds_in_netrc_modified_command(self, helper):
        """Credentials must not appear in the modified command string."""
        result = await helper.prepare_execution(
            "example.com", "curl", "curl https://example.com/api"
        )
        assert result is not None
        assert "s3cret" not in result.modified_command
        assert "user@test.com" not in result.modified_command
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_no_creds_in_git_modified_command(self, helper):
        result = await helper.prepare_execution(
            "github.com", "git", "git clone https://github.com/org/repo.git"
        )
        assert result is not None
        assert "s3cret" not in result.modified_command
        assert "user@test.com" not in result.modified_command
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_cleanup_removes_all_files(self, helper):
        result = await helper.prepare_execution(
            "example.com", "curl", "curl https://example.com"
        )
        assert result is not None
        paths = list(result.cleanup_paths)
        for p in paths:
            assert p.exists()
        BashCredentialHelper.cleanup(result)
        for p in paths:
            assert not p.exists()

    def test_cleanup_handles_missing_files(self):
        """cleanup() should not raise if files are already gone."""
        execution = AuthenticatedExecution(
            strategy="netrc",
            domain="example.com",
            modified_command="curl https://example.com",
            cleanup_paths=[Path("/tmp/.clawbot-nonexistent-cleanup-test")],
        )
        # Should not raise
        BashCredentialHelper.cleanup(execution)

    @pytest.mark.asyncio
    async def test_no_credential_manager_returns_none(self):
        helper = BashCredentialHelper(credential_manager=None)
        result = await helper.prepare_execution(
            "example.com", "curl", "curl https://example.com"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_credentials_returns_none(self, helper_no_creds):
        result = await helper_no_creds.prepare_execution(
            "example.com", "curl", "curl https://example.com"
        )
        assert result is None


# ── Wiring ──────────────────────────────────────────────────────


class TestWiring:
    @pytest.mark.asyncio
    async def test_set_credential_manager_post_init(self):
        helper = BashCredentialHelper()  # no credential_manager
        assert await helper.prepare_execution(
            "x.com", "curl", "curl https://x.com"
        ) is None

        cm = _mock_cred_manager(_DEFAULT_CREDS)
        helper.set_credential_manager(cm)

        result = await helper.prepare_execution(
            "x.com", "curl", "curl https://x.com"
        )
        assert result is not None
        assert result.strategy == "netrc"
        BashCredentialHelper.cleanup(result)

    @pytest.mark.asyncio
    async def test_prepare_without_manager_returns_none(self):
        helper = BashCredentialHelper()
        result = await helper.prepare_execution(
            "x.com", "gh", "gh pr list"
        )
        assert result is None


# ── Insert Flag Helper ──────────────────────────────────────────


class TestInsertFlagHelper:
    def test_inserts_after_curl(self):
        result = BashCredentialHelper._insert_flag_after_tool(
            "curl -sL https://example.com", ["curl"], "--netrc-file /tmp/x"
        )
        assert result == "curl --netrc-file /tmp/x -sL https://example.com"

    def test_inserts_after_wget_in_pipe(self):
        result = BashCredentialHelper._insert_flag_after_tool(
            "echo url | wget -i -", ["wget"], "--netrc-file /tmp/x"
        )
        assert "wget --netrc-file /tmp/x" in result

    def test_fallback_when_tool_not_found(self):
        result = BashCredentialHelper._insert_flag_after_tool(
            "unknown-tool https://example.com", ["curl", "wget"], "--flag /tmp/x"
        )
        assert result.startswith("--flag /tmp/x")
