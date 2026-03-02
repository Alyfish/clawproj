"""
ClawBot Code Execution Tool

Executes Python or JavaScript code in an isolated subprocess.

Security notes (MVP):
    - Uses subprocess isolation — acceptable for single-user, self-hosted.
    - Production MUST use: E2B Sandbox, Docker, or Firecracker microVM.
    - Current limitations:
        * No network restriction (code can make HTTP requests)
        * No filesystem restriction beyond cwd (code runs in temp dir)
        * No memory limit (OS-level ulimits are the only guard)
    - Code CAN access stdlib (json, csv, math, datetime, re, etc.)
    - Code CANNOT access project files (cwd is an isolated temp dir)
    - Environment is stripped to prevent credential leakage

PRODUCTION TODO:
    Replace subprocess with E2B Sandbox (https://github.com/e2b-dev/code-interpreter)
    or Docker for proper isolation. E2B API:
        sandbox = await AsyncSandbox.create()
        execution = await sandbox.run_code(code, language="python")

Design references:
    - OpenManus PythonExecute (multiprocessing + stdout capture + timeout)
    - claw0/learn-claude-code s02_tool_use (subprocess, 120s timeout, 50KB truncation)
    - E2B Code Interpreter (AsyncSandbox.run_code — production upgrade path)
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from server.agent.tools.tool_registry import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# Maximum output size per stream (stdout/stderr) — 50KB
# Matches claw0 and learn-claude-code truncation limits.
_MAX_OUTPUT_BYTES = 50_000

# Allowed environment variables to pass to the subprocess.
# NEVER include credentials (ANTHROPIC_API_KEY, CLAWBOT_CRED_*, etc.)
_SAFE_ENV_KEYS = {"PATH", "HOME", "LANG", "TMPDIR", "LC_ALL"}


def _safe_env() -> dict[str, str]:
    """Build a minimal environment dict for the subprocess.

    Starts from an empty dict and copies only safe keys from os.environ.
    This prevents credential leakage (API keys, tokens, etc.) into
    user-submitted code.

    PRODUCTION TODO: Replace subprocess with E2B Sandbox
    (https://github.com/e2b-dev/code-interpreter) or Docker
    for proper isolation.
    """
    env: dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


class CodeExecutionTool(BaseTool):
    """Execute Python or JavaScript code in a sandboxed subprocess.

    The LLM calls this tool when it needs to:
    - Process or transform data (parse JSON, CSV, calculate stats)
    - Run computations (math, date arithmetic, scoring algorithms)
    - Generate content (format text, build structured output)
    - Test code snippets before presenting to the user

    Each execution runs in a fresh temp directory with a stripped
    environment. Output is captured and truncated to prevent
    context window overflow.
    """

    @property
    def name(self) -> str:
        return "code_execution"

    @property
    def description(self) -> str:
        return (
            "Execute Python or JavaScript code in a sandbox. "
            "Use for data processing, calculations, parsing API "
            "responses, or generating content."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "language": {
                "type": "string",
                "required": True,
                "description": "Programming language: 'python' or 'javascript'",
                "enum": ["python", "javascript"],
            },
            "code": {
                "type": "string",
                "required": True,
                "description": "The code to execute. Use print() to produce output.",
            },
            "timeout": {
                "type": "integer",
                "required": False,
                "description": (
                    "Max execution time in seconds (default: 30, max: 120). "
                    "Long-running code is killed after this limit."
                ),
            },
        }

    async def execute(
        self,
        language: str = "python",
        code: str = "",
        timeout: int = 30,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute code and return stdout, stderr, exit code, and elapsed time.

        Args:
            language: "python" or "javascript"
            code: Source code to run
            timeout: Max seconds before killing the process (1–120)

        Returns:
            ToolResult with output dict: {stdout, stderr, exit_code, elapsed_ms}
        """
        # -- Validate inputs --
        if language not in ("python", "javascript"):
            return self.fail(
                f"Unsupported language: {language!r}. Use 'python' or 'javascript'."
            )

        if not code or not code.strip():
            return self.fail("No code provided.")

        # Clamp timeout
        timeout = max(1, min(int(timeout), 120))

        # -- Set up temp directory --
        temp_dir = tempfile.mkdtemp(prefix="clawbot_exec_")
        try:
            return await self._run_in_subprocess(
                language, code, timeout, temp_dir
            )
        finally:
            # Always clean up, even on unexpected errors
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def _run_in_subprocess(
        self,
        language: str,
        code: str,
        timeout: int,
        temp_dir: str,
    ) -> ToolResult:
        """Write code to a temp file and run it in a subprocess."""
        # -- Write code to temp file --
        if language == "python":
            script_name = "script.py"
            cmd = ["python3", str(Path(temp_dir) / script_name)]
        else:
            script_name = "script.js"
            cmd = ["node", str(Path(temp_dir) / script_name)]

        script_path = Path(temp_dir) / script_name
        script_path.write_text(code, encoding="utf-8")

        # -- Execute --
        start_time = time.monotonic()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=temp_dir,
                env=_safe_env(),
            )
        except FileNotFoundError:
            runtime = "python3" if language == "python" else "node"
            return self.fail(
                f"Runtime not found: {runtime}. "
                f"Ensure {runtime} is installed and in PATH."
            )
        except OSError as e:
            return self.fail(f"Failed to start subprocess: {e}")

        # -- Wait with timeout --
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            # Kill the process and wait for it to actually terminate
            process.kill()
            await process.wait()
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return self.fail(
                f"Code execution timed out after {timeout}s "
                f"(elapsed: {elapsed_ms}ms). "
                f"Consider optimizing the code or increasing the timeout."
            )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # -- Decode and truncate output --
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        stdout_truncated = len(stdout) > _MAX_OUTPUT_BYTES
        stderr_truncated = len(stderr) > _MAX_OUTPUT_BYTES

        if stdout_truncated:
            stdout = stdout[:_MAX_OUTPUT_BYTES] + "\n... (output truncated at 50KB)"
        if stderr_truncated:
            stderr = stderr[:_MAX_OUTPUT_BYTES] + "\n... (stderr truncated at 50KB)"

        exit_code = process.returncode or 0

        logger.info(
            "Code execution: lang=%s exit=%d elapsed=%dms stdout=%d stderr=%d",
            language,
            exit_code,
            elapsed_ms,
            len(stdout),
            len(stderr),
        )

        # Direct constructor: success depends on exit_code, and we need BOTH
        # output and error populated simultaneously — self.success()/self.fail()
        # can't express this (one sets error=None, the other sets output=None).
        return ToolResult(
            success=exit_code == 0,
            output={
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "elapsed_ms": elapsed_ms,
            },
            error=stderr.strip() if exit_code != 0 else None,
        )
