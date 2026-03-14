"""
ClawBot Bash Credential Helper — Secure Credential Injection for CLI Tools

Injects credentials into bash commands via tool-specific secure mechanisms
(netrc files, credential helper scripts, stdin pipes, env vars).  Credentials
NEVER appear in command arguments (visible in /proc) or in log output.

Security layers:
  1. Temp files   — 0o600 perms, UUID names in /tmp, always deleted in finally
  2. Nil-on-use   — all credential vars set to None after injection
  3. Memory-only   — token cache never persisted to disk
  4. Log-safe      — only domain + strategy logged, never credential values
  5. Script-safe   — GIT_ASKPASS scripts reference env vars, not literal creds
"""
from __future__ import annotations

import logging
import os
import stat
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# AUTHENTICATED EXECUTION RECIPE
# ------------------------------------------------------------------


@dataclass
class AuthenticatedExecution:
    """Internal recipe for running a command with injected credentials.

    This dataclass NEVER reaches Claude — it is consumed entirely within
    BashExecuteTool.execute() and cleaned up in a finally block.
    """

    strategy: str  # "netrc", "git_credential", "gh_token", "npm_token", "docker_stdin", "env"
    domain: str
    modified_command: str  # Command with auth flags/wrapping added
    env_additions: dict[str, str] = field(default_factory=dict)
    stdin_input: str | None = None
    setup_files: list[Path] = field(default_factory=list)
    cleanup_paths: list[Path] = field(default_factory=list)


# ------------------------------------------------------------------
# TOOL → STRATEGY MAPPING
# ------------------------------------------------------------------

_TOOL_STRATEGIES: dict[str, str] = {
    "curl": "netrc",
    "wget": "netrc",
    "httpie": "netrc",
    "http": "netrc",  # httpie binary name
    "git": "git_credential",
    "gh": "gh_token",
    "npm": "npm_token",
    "docker": "docker_stdin",
    "generic": "env",
}

# GIT_ASKPASS script — reads credentials from env vars, never embeds
# literal passwords in the file itself.
_GIT_ASKPASS_SCRIPT = (
    '#!/bin/sh\n'
    'case "$1" in\n'
    '  *sername*) echo "$_CLAWBOT_GIT_USER";;\n'
    '  *assword*) echo "$_CLAWBOT_GIT_PASS";;\n'
    '  *) echo "$_CLAWBOT_GIT_PASS";;\n'
    'esac\n'
)


# ------------------------------------------------------------------
# HELPER
# ------------------------------------------------------------------


class BashCredentialHelper:
    """Secure credential injection for bash commands.

    Consumes credentials from CredentialManager and produces an
    AuthenticatedExecution recipe that BashExecuteTool uses to run
    authenticated subprocess commands.

    Called internally by BashExecuteTool — never by Claude directly.
    """

    def __init__(
        self,
        credential_manager: Any = None,
        session_cache: Any = None,
    ) -> None:
        self._credential_manager = credential_manager
        self._session_cache = session_cache
        self._token_cache: dict[str, dict[str, Any]] = {}
        self._failed_domains: set[str] = set()

    def set_credential_manager(self, cm: Any) -> None:
        """Post-init wiring (same pattern as CredentialManager.set_gateway_client)."""
        self._credential_manager = cm

    # ── Token Cache ─────────────────────────────────────────────

    def get_cached_token(self, domain: str) -> str | None:
        """Return cached token for domain if not expired, else None."""
        entry = self._token_cache.get(domain)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            del self._token_cache[domain]
            return None
        return entry["token"]

    def cache_token(self, domain: str, token: str, ttl: float = 3600.0) -> None:
        """Cache a token in memory (never persisted to disk)."""
        self._token_cache[domain] = {
            "token": token,
            "expires_at": time.time() + ttl,
        }

    # ── Main Entry Point ────────────────────────────────────────

    async def prepare_execution(
        self,
        domain: str,
        tool_hint: str,
        command: str,
        reason: str = "",
        timeout: float = 30.0,
    ) -> AuthenticatedExecution | None:
        """Request credentials and build an authenticated execution recipe.

        Args:
            domain: Domain to authenticate against (e.g. "github.com").
            tool_hint: CLI tool name — curl, wget, git, gh, npm, docker, generic.
            command: Original bash command.
            reason: Why auth is needed (shown to user on iOS).
            timeout: Credential request timeout in seconds.

        Returns:
            AuthenticatedExecution with modified command + env + temp files,
            or None if credentials are unavailable.

        SECURITY: Caller MUST call cleanup() in a finally block.
        """
        if self._credential_manager is None:
            logger.warning("BashCredentialHelper: no credential_manager wired")
            return None

        if domain in self._failed_domains:
            logger.info(
                "Skipping credential request for failed domain=%s", domain
            )
            return None

        strategy = _TOOL_STRATEGIES.get(tool_hint, "env")

        # 1. Check token cache for token-based strategies
        cached_token = self.get_cached_token(domain)
        if cached_token and strategy in ("gh_token", "npm_token"):
            logger.info(
                "Using cached token: domain=%s strategy=%s", domain, strategy
            )
            return self._build_token_strategy(strategy, domain, command, cached_token)

        # 2. Request credentials from iOS
        cred_reason = reason or f"CLI authentication needed for {domain}"
        credentials = await self._credential_manager.request_credentials(
            domain, cred_reason, timeout,
        )
        if not credentials:
            logger.info(
                "No credentials available: domain=%s strategy=%s", domain, strategy
            )
            return None

        cred = credentials[0]
        username = cred.get("username", "")
        password = cred.get("password", "")

        try:
            logger.info(
                "Building credential injection: domain=%s strategy=%s",
                domain, strategy,
            )

            if strategy == "netrc":
                return self._build_netrc(domain, command, username, password)
            elif strategy == "git_credential":
                return self._build_git_credential(
                    domain, command, username, password
                )
            elif strategy == "gh_token":
                return self._build_gh_token(domain, command, password)
            elif strategy == "npm_token":
                return self._build_npm_token(domain, command, password)
            elif strategy == "docker_stdin":
                return self._build_docker_stdin(
                    domain, command, username, password
                )
            else:  # "env"
                return self._build_env_vars(domain, command, username, password)
        finally:
            # SECURITY: nil all credential references
            credentials = None  # noqa: F841
            cred = None  # noqa: F841
            username = None  # noqa: F841
            password = None  # noqa: F841

    # ── Strategy Builders ───────────────────────────────────────

    def _build_netrc(
        self,
        domain: str,
        command: str,
        username: str,
        password: str,
    ) -> AuthenticatedExecution:
        """curl/wget/httpie: temp .netrc file with --netrc-file flag."""
        netrc_path = Path(f"/tmp/.clawbot-netrc-{uuid.uuid4().hex[:12]}")
        netrc_content = (
            f"machine {domain}\nlogin {username}\npassword {password}\n"
        )

        netrc_path.write_text(netrc_content, encoding="utf-8")
        os.chmod(str(netrc_path), stat.S_IRUSR | stat.S_IWUSR)  # 0o600

        modified = self._insert_flag_after_tool(
            command, ["curl", "wget", "http"], f"--netrc-file {netrc_path}"
        )

        return AuthenticatedExecution(
            strategy="netrc",
            domain=domain,
            modified_command=modified,
            setup_files=[netrc_path],
            cleanup_paths=[netrc_path],
        )

    @staticmethod
    def _build_git_credential(
        domain: str,
        command: str,
        username: str,
        password: str,
    ) -> AuthenticatedExecution:
        """git: GIT_ASKPASS script that reads from env vars (never embeds creds)."""
        helper_path = Path(f"/tmp/.clawbot-git-cred-{uuid.uuid4().hex[:12]}")

        helper_path.write_text(_GIT_ASKPASS_SCRIPT, encoding="utf-8")
        os.chmod(str(helper_path), stat.S_IRWXU)  # 0o700

        return AuthenticatedExecution(
            strategy="git_credential",
            domain=domain,
            modified_command=command,
            env_additions={
                "GIT_ASKPASS": str(helper_path),
                "GIT_TERMINAL_PROMPT": "0",
                "_CLAWBOT_GIT_USER": username,
                "_CLAWBOT_GIT_PASS": password,
            },
            setup_files=[helper_path],
            cleanup_paths=[helper_path],
        )

    def _build_gh_token(
        self,
        domain: str,
        command: str,
        token: str,
    ) -> AuthenticatedExecution:
        """gh CLI: GH_TOKEN env var (standard GitHub CLI auth)."""
        self.cache_token(domain, token)

        return AuthenticatedExecution(
            strategy="gh_token",
            domain=domain,
            modified_command=command,
            env_additions={"GH_TOKEN": token},
        )

    def _build_npm_token(
        self,
        domain: str,
        command: str,
        token: str,
    ) -> AuthenticatedExecution:
        """npm: NPM_TOKEN env var."""
        self.cache_token(domain, token)

        return AuthenticatedExecution(
            strategy="npm_token",
            domain=domain,
            modified_command=command,
            env_additions={"NPM_TOKEN": token},
        )

    @staticmethod
    def _build_docker_stdin(
        domain: str,
        command: str,
        username: str,
        password: str,
    ) -> AuthenticatedExecution:
        """docker: pipe password via stdin with --password-stdin flag."""
        login_cmd = (
            f"docker login --username '{username}' --password-stdin {domain}"
        )
        modified = f"{login_cmd} && {command}"

        return AuthenticatedExecution(
            strategy="docker_stdin",
            domain=domain,
            modified_command=modified,
            stdin_input=password,
        )

    @staticmethod
    def _build_env_vars(
        domain: str,
        command: str,
        username: str,
        password: str,
    ) -> AuthenticatedExecution:
        """Generic fallback: CLAWBOT_USER + CLAWBOT_PASS env vars."""
        return AuthenticatedExecution(
            strategy="env",
            domain=domain,
            modified_command=command,
            env_additions={
                "CLAWBOT_USER": username,
                "CLAWBOT_PASS": password,
            },
        )

    def _build_token_strategy(
        self,
        strategy: str,
        domain: str,
        command: str,
        token: str,
    ) -> AuthenticatedExecution:
        """Build execution from a cached token (no credential request)."""
        if strategy == "gh_token":
            return AuthenticatedExecution(
                strategy="gh_token",
                domain=domain,
                modified_command=command,
                env_additions={"GH_TOKEN": token},
            )
        elif strategy == "npm_token":
            return AuthenticatedExecution(
                strategy="npm_token",
                domain=domain,
                modified_command=command,
                env_additions={"NPM_TOKEN": token},
            )
        # Fallback
        return AuthenticatedExecution(
            strategy=strategy,
            domain=domain,
            modified_command=command,
            env_additions={"CLAWBOT_TOKEN": token},
        )

    # ── Failure Tracking ──────────────────────────────────────────

    def record_credential_failure(self, domain: str) -> None:
        """Mark credentials for a domain as invalid for this session.

        Prevents re-requesting the same wrong credentials. Clears
        any cached token for the domain.
        """
        self._failed_domains.add(domain)
        self._token_cache.pop(domain, None)

    def clear_cache(self) -> None:
        """Clear token cache and failed-domain set.

        Called during Agent.shutdown().
        """
        self._token_cache.clear()
        self._failed_domains.clear()
        logger.info("Bash credential cache cleared")

    # ── Cleanup ─────────────────────────────────────────────────

    @staticmethod
    def cleanup(execution: AuthenticatedExecution) -> None:
        """Delete all temp files created during credential injection.

        MUST be called in a finally block after command execution.
        """
        for path in execution.cleanup_paths:
            try:
                if path.exists():
                    path.unlink()
                    logger.debug("Cleaned up credential temp file: %s", path.name)
            except OSError as e:
                logger.warning("Failed to cleanup %s: %s", path.name, e)

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _insert_flag_after_tool(
        command: str,
        tool_names: list[str],
        flag: str,
    ) -> str:
        """Insert a flag immediately after the CLI tool name in a command.

        Example: "curl -sL https://..." → "curl --netrc-file /tmp/x -sL https://..."
        """
        for name in tool_names:
            idx = command.find(name)
            if idx >= 0:
                insert_pos = idx + len(name)
                return command[:insert_pos] + f" {flag}" + command[insert_pos:]
        # Tool not found in command — prepend flag (best effort)
        return f"{flag} && {command}"
