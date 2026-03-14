"""
ClawBot Bash Execute Tool

Gives the agent a shell for running bash commands in its sandboxed
container.  This is the agent's primary tool — it should default to
bash unless a structured tool's specific output format is needed.

Security layers:
  1. Blocklist  — dangerous patterns rejected before execution
  2. Approval   — risky patterns gate on user approval first
  3. Env filter — only whitelisted env vars reach the subprocess
  4. Timeout    — hard kill after configurable seconds
  5. Truncation — stdout/stderr capped to prevent context blow-up
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from server.agent.tools.tool_registry import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# CONSTANTS
# ------------------------------------------------------------------

MAX_STDOUT = 50_000  # 50 KB
MAX_STDERR = 10_000  # 10 KB
TRUNCATION_MSG = (
    "\n[Output truncated. Save to file and use head/tail/grep to read parts.]"
)

DEFAULT_WORKING_DIR = "/workspace"
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120

# ------------------------------------------------------------------
# SECURITY BLOCKLIST — reject before running
# ------------------------------------------------------------------

_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?/($|\s|/)", re.IGNORECASE),
        "Destructive rm on root filesystem",
    ),
    (
        re.compile(r":\(\)\s*\{.*\|.*&.*\}\s*;*\s*:", re.IGNORECASE),
        "Fork bomb",
    ),
    (
        re.compile(r"\|\s*(ba)?sh($|\s)", re.IGNORECASE),
        "Piping into shell",
    ),
    (
        re.compile(r">\s*/etc/", re.IGNORECASE),
        "Writing to /etc",
    ),
    (
        re.compile(r"cat\s+/etc/(shadow|passwd)", re.IGNORECASE),
        "Reading sensitive system files",
    ),
    (
        re.compile(r"(nmap|masscan|nikto)\s", re.IGNORECASE),
        "Network scanning tool",
    ),
    (
        re.compile(r"(xmrig|minerd|cgminer)", re.IGNORECASE),
        "Cryptocurrency miner",
    ),
    (
        re.compile(r"(nsenter|chroot)\s", re.IGNORECASE),
        "Container escape attempt",
    ),
    (
        re.compile(r"mkfs\.", re.IGNORECASE),
        "Filesystem format command",
    ),
]

# ------------------------------------------------------------------
# APPROVAL TRIGGERS — call request_approval before running
# ------------------------------------------------------------------

_APPROVAL_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # Payment URLs
    (
        re.compile(
            r"(stripe\.com|paypal\.com|checkout|payment)", re.IGNORECASE
        ),
        "pay",
        "Command accesses payment service",
    ),
    # Destructive rm on user data (not /tmp, not cache)
    (
        re.compile(
            r"rm\s+(-[a-zA-Z]*\s+)*(?!/tmp)(?!/workspace/data/cache)"
            r"/\S*\S",
            re.IGNORECASE,
        ),
        "delete",
        "Command deletes files",
    ),
    # Email sending
    (
        re.compile(
            r"(sendmail|msmtp|sendgrid\.com|mailgun\.net|ses\.amazonaws\.com"
            r"|api\.mailchimp\.com)",
            re.IGNORECASE,
        ),
        "send",
        "Command sends email",
    ),
]

# ------------------------------------------------------------------
# ENVIRONMENT FILTERING
# ------------------------------------------------------------------

# Only these vars pass through to the subprocess.
_ALLOWED_ENV_VARS: dict[str, str | None] = {
    # None = read from os.environ; str = hardcoded value
    "PATH": None,
    "HOME": None,
    "LANG": "C.UTF-8",
    "PYTHONUNBUFFERED": "1",
    "CLAWBOT_SEARXNG_URL": None,
    "TERM": "xterm-256color",
    "WORKSPACE": DEFAULT_WORKING_DIR,
}

# Var names containing these substrings (case-insensitive) are blocked
# even if they somehow end up in the whitelist.
_BLOCKED_ENV_SUBSTRINGS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def _build_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a filtered environment dict for the subprocess.

    Args:
        extra: Additional env vars from trusted credential pipeline
            (BashCredentialHelper).  These bypass the blocked-substring
            filter because they originate from internal code, not
            untrusted input.
    """
    env: dict[str, str] = {}
    for name, default in _ALLOWED_ENV_VARS.items():
        # Safety: never pass through vars with secret-like names
        if any(sub in name.upper() for sub in _BLOCKED_ENV_SUBSTRINGS):
            continue
        value = default if default is not None else os.environ.get(name)
        if value is not None:
            env[name] = value
    if extra:
        env.update(extra)
    return env


def _is_gws_command(command: str) -> bool:
    """Check if a command invokes the gws CLI."""
    stripped = command.strip()
    return stripped.startswith("gws ") or stripped == "gws"


# ------------------------------------------------------------------
# TOOL
# ------------------------------------------------------------------


class BashExecuteTool(BaseTool):
    """Execute bash commands in the agent's sandboxed container."""

    def __init__(self, gateway_client: Optional[Any] = None) -> None:
        self._gateway_client = gateway_client
        self._bash_credential_helper: Optional[Any] = None

    def set_gateway_client(self, client: Any) -> None:
        """Wire gateway client after initialization."""
        self._gateway_client = client

    def set_bash_credential_helper(self, helper: Any) -> None:
        """Wire BashCredentialHelper after initialization."""
        self._bash_credential_helper = helper

    # -- metadata --------------------------------------------------

    @property
    def name(self) -> str:
        return "bash_execute"

    @property
    def description(self) -> str:
        return (
            "Execute bash commands in the agent's sandboxed container.\n"
            "This is your primary tool. Default to it unless you need "
            "a structured tool's specific output format.\n\n"
            "Your environment:\n"
            "- Working directory: /workspace (persistent across sessions)\n"
            "- Web search: curl -s "
            "'http://searxng:8080/search?q=QUERY&format=json' "
            "| jq '.results[:5]'\n"
            "- Tools: Python 3, Node.js, jq, curl, grep, awk, sed, "
            "pip, npm\n"
            "- Memory: /workspace/memory/ "
            "(markdown + YAML frontmatter)\n"
            "- Scripts: /workspace/scripts/ "
            "(reusable code you create)\n"
            "- Data: /workspace/data/ "
            "(downloads, API responses, temp files)\n\n"
            "Compose with pipes. Chain with &&. "
            "Save intermediate results to files when pipelines get "
            "complex. Save reusable scripts to /workspace/scripts/."
        )

    @property
    def requires_approval(self) -> list[str]:
        return ["pay", "send", "delete"]

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "command": {
                "type": "string",
                "required": True,
                "description": "Bash command or pipeline to execute.",
            },
            "timeout": {
                "type": "integer",
                "required": False,
                "description": (
                    "Max execution time in seconds (default 30, max 120)."
                ),
            },
            "working_dir": {
                "type": "string",
                "required": False,
                "description": (
                    "Working directory for the command "
                    "(default /workspace)."
                ),
            },
            "authenticate": {
                "type": "object",
                "required": False,
                "description": (
                    "Inject credentials securely before running. "
                    "Provide {domain, tool_hint, reason}. "
                    "tool_hint: curl, wget, git, gh, npm, docker, generic. "
                    "Credentials injected via netrc files, env vars, or "
                    "stdin — NEVER as command arguments."
                ),
                "properties": {
                    "domain": {
                        "type": "string",
                        "description": "Domain to authenticate against.",
                    },
                    "tool_hint": {
                        "type": "string",
                        "description": (
                            "CLI tool: curl, wget, git, gh, npm, "
                            "docker, generic."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why auth is needed (shown to user).",
                    },
                },
            },
        }

    # -- execution -------------------------------------------------

    async def execute(
        self,
        command: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        working_dir: str = DEFAULT_WORKING_DIR,
        **kwargs: Any,
    ) -> ToolResult:
        # 1. Validate command
        if not command or not command.strip():
            return self.fail("No command provided")

        # 2. Clamp timeout
        timeout = max(1, min(int(timeout), MAX_TIMEOUT))

        # 3. Resolve working dir — create if missing
        work_path = Path(working_dir)
        try:
            work_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # may not have perms; subprocess will fail naturally

        # 4. Security blocklist
        blocked = self._check_blocked(command)
        if blocked:
            logger.warning("Blocked command: %s — %s", command[:80], blocked)
            return self.fail(f"Blocked: {blocked}")

        # 5. Approval triggers
        approval_needed = self._check_approval(command)
        if approval_needed:
            action, summary = approval_needed
            if self._gateway_client is None:
                return self.fail(
                    f"Command requires approval ({action}: {summary}) "
                    "but approval system is not configured. "
                    "Cannot proceed without user approval."
                )
            try:
                result = await self._gateway_client.request_approval(
                    action, summary, {"command": command}
                )
                if not result.get("approved", False):
                    msg = result.get("message", "")
                    return self.fail(
                        f"Command denied by user ({action}). {msg}".strip()
                    )
                logger.info(
                    "Approval granted for bash command: action=%s", action
                )
            except Exception as e:
                logger.warning("Approval request failed: %s", e)
                return self.fail(
                    f"Approval request failed: {e}. "
                    "Cannot proceed without user approval."
                )

        # 5.5 Credential injection (authenticate parameter)
        auth_execution = None
        auth_param = kwargs.get("authenticate")
        if auth_param and isinstance(auth_param, dict) and self._bash_credential_helper:
            try:
                auth_execution = await self._bash_credential_helper.prepare_execution(
                    domain=auth_param.get("domain", ""),
                    tool_hint=auth_param.get("tool_hint", "generic"),
                    command=command,
                    reason=auth_param.get("reason", ""),
                )
                if auth_execution:
                    command = auth_execution.modified_command
            except Exception as e:
                logger.warning("Credential injection failed: %s", e)

        try:
            # 6. Build filtered env (auth + gws token bypass blocked-substring filter)
            extra_env: dict[str, str] = {}
            if _is_gws_command(command):
                gws_token = os.environ.get("GOOGLE_WORKSPACE_CLI_TOKEN")
                if gws_token:
                    extra_env["GOOGLE_WORKSPACE_CLI_TOKEN"] = gws_token
            if auth_execution and auth_execution.env_additions:
                extra_env.update(auth_execution.env_additions)
            env = _build_env(extra=extra_env or None)

            # 7. Run subprocess
            stdin_data = None
            if auth_execution and auth_execution.stdin_input:
                stdin_data = auth_execution.stdin_input.encode("utf-8")

            try:
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.PIPE if stdin_data else None,
                    cwd=str(work_path),
                    env=env,
                )
            except Exception as e:
                return self.fail(f"Failed to start process: {e}")

            # 8. Wait with timeout
            timed_out = False
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(input=stdin_data), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                timed_out = True
                stdout_bytes = b""
                stderr_bytes = b""

            # 9. Decode and truncate
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            truncated = False

            if len(stdout) > MAX_STDOUT:
                stdout = stdout[:MAX_STDOUT] + TRUNCATION_MSG
                truncated = True
            if len(stderr) > MAX_STDERR:
                stderr = stderr[:MAX_STDERR] + TRUNCATION_MSG
                truncated = True

            exit_code = process.returncode if not timed_out else -1

            # 9.5 Output size hints — teach the agent to save-to-file
            hint = ""
            stdout_len = len(stdout)
            if stdout_len > 20_000:
                hint = (
                    f"\n\n[Warning: Very large output ({stdout_len // 1000}KB). "
                    "Next time, redirect to file: "
                    "command > /workspace/data/output.json && "
                    "jq '.key' /workspace/data/output.json]"
                )
            elif stdout_len > 5_000:
                hint = (
                    "\n\n[Hint: Large output. Consider saving to "
                    "/workspace/data/ and using jq/grep to extract "
                    "specific parts.]"
                )

            # 10. Return result
            output = {
                "stdout": stdout + hint,
                "stderr": stderr,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "truncated": truncated,
            }

            if timed_out:
                return ToolResult(
                    success=False,
                    output=output,
                    error=f"Command timed out after {timeout}s",
                )

            return ToolResult(
                success=exit_code == 0,
                output=output,
                error=stderr.strip() if exit_code != 0 else None,
            )
        finally:
            # Cleanup credential temp files
            if auth_execution:
                from server.agent.tools.bash_credential_helper import (
                    BashCredentialHelper,
                )
                BashCredentialHelper.cleanup(auth_execution)
                auth_execution = None

    # -- credential retry ------------------------------------------

    async def execute_authenticated(
        self,
        execution: Any,
        timeout: int = DEFAULT_TIMEOUT,
        working_dir: str = DEFAULT_WORKING_DIR,
    ) -> ToolResult:
        """Re-execute a command using an AuthenticatedExecution recipe.

        Internal method — NOT exposed as a tool parameter.
        Called by agent.py auth retry logic after AuthDetector
        identifies an authentication failure.

        Skips blocklist/approval checks (already passed on first attempt).

        Args:
            execution: AuthenticatedExecution recipe from BashCredentialHelper.
                Contains modified_command, env_additions, stdin_input,
                and cleanup_paths.
            timeout: Max execution time in seconds.
            working_dir: Working directory for the command.

        SECURITY:
          env_additions bypass the blocked-substring filter via
          ``_build_env(extra=...)``.  Temp files (netrc, GIT_ASKPASS)
          are cleaned up by the caller via BashCredentialHelper.cleanup().
        """
        timeout = max(1, min(int(timeout), MAX_TIMEOUT))
        work_path = Path(working_dir)
        try:
            work_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        env = _build_env(extra=execution.env_additions or None)
        stdin_data = (
            execution.stdin_input.encode("utf-8")
            if execution.stdin_input
            else None
        )

        try:
            process = await asyncio.create_subprocess_shell(
                execution.modified_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin_data else None,
                cwd=str(work_path),
                env=env,
            )
        except Exception as e:
            return self.fail(f"Failed to start process: {e}")

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=stdin_data), timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            timed_out = True
            stdout_bytes = b""
            stderr_bytes = b""

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        truncated = False

        if len(stdout) > MAX_STDOUT:
            stdout = stdout[:MAX_STDOUT] + TRUNCATION_MSG
            truncated = True
        if len(stderr) > MAX_STDERR:
            stderr = stderr[:MAX_STDERR] + TRUNCATION_MSG
            truncated = True

        exit_code = process.returncode if not timed_out else -1

        output = {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "truncated": truncated,
        }

        if timed_out:
            return ToolResult(
                success=False,
                output=output,
                error=f"Command timed out after {timeout}s",
            )

        return ToolResult(
            success=exit_code == 0,
            output=output,
            error=stderr.strip() if exit_code != 0 else None,
        )

    # -- helpers ---------------------------------------------------

    @staticmethod
    def _check_blocked(command: str) -> str | None:
        """Return reason string if command matches blocklist, else None."""
        for pattern, reason in _BLOCKED_PATTERNS:
            if pattern.search(command):
                return reason
        return None

    @staticmethod
    def _check_approval(
        command: str,
    ) -> tuple[str, str] | None:
        """Return (action, summary) if command needs approval, else None."""
        for pattern, action, summary in _APPROVAL_PATTERNS:
            if pattern.search(command):
                return action, summary
        return None
