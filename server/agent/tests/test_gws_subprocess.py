"""Verify gws CLI works when invoked via subprocess (matching bash_execute pattern).

These tests require gws to be installed in the environment.
Run inside the agent container:
    docker exec clawbot-agent pytest /app/server/agent/tests/test_gws_subprocess.py -v
"""
import subprocess
import json
import os
import shutil

import pytest

# Skip entire module if gws is not installed
pytestmark = pytest.mark.skipif(
    shutil.which("gws") is None,
    reason="gws CLI not installed (run inside agent container)",
)


def test_gws_binary_exists():
    """gws binary is on PATH and executable."""
    result = subprocess.run(["which", "gws"], capture_output=True, text=True)
    assert result.returncode == 0, "gws not found on PATH"


def test_gws_version():
    """gws --version runs successfully."""
    result = subprocess.run(
        ["gws", "--version"], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, f"gws --version failed: {result.stderr}"


def test_gws_dry_run_with_token_env():
    """gws reads GOOGLE_WORKSPACE_CLI_TOKEN from subprocess env."""
    env = {**os.environ, "GOOGLE_WORKSPACE_CLI_TOKEN": "test-token-subprocess"}
    result = subprocess.run(
        [
            "gws", "drive", "files", "list",
            "--params", '{"pageSize":1}',
            "--dry-run",
        ],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, (
        f"dry-run failed (exit {result.returncode}): {result.stderr}"
    )
    output = json.loads(result.stdout)
    assert output.get("dry_run") is True
    assert "googleapis.com" in output.get("url", "")


def test_gws_exit_code_2_on_auth_failure():
    """gws returns exit code 2 when no credentials are provided."""
    env = {k: v for k, v in os.environ.items() if "GOOGLE" not in k}
    result = subprocess.run(
        [
            "gws", "drive", "files", "list",
            "--params", '{"pageSize":1}',
        ],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 2, (
        f"Expected exit 2 (auth error), got {result.returncode}: {result.stderr}"
    )
