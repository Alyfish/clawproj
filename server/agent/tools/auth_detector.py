"""
ClawBot Auth Detector — Bash Output Authentication Failure Detection

Detects authentication failures in bash command stdout/stderr by matching
against known patterns for HTTP, GitHub CLI, git, npm, docker, and SSH.

Stateless utility class — all methods are classmethods.
"""
from __future__ import annotations

import re
from typing import Any


class AuthDetector:
    """Detect authentication failures in bash command output.

    Usage::

        info = AuthDetector.detect(stdout, stderr, exit_code, command)
        if info:
            print(f"Auth failure: {info['tool']} at {info['domain']}")
    """

    # (compiled_regex, tool_type, confidence)
    _PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
        # ── HTTP 401/403 ──────────────────────────────────────────
        (re.compile(r"HTTP[/ ]\d+(?:\.\d+)?\s+401\b", re.I), "http", 0.95),
        (re.compile(r"HTTP[/ ]\d+(?:\.\d+)?\s+403\b", re.I), "http", 0.7),
        (re.compile(r'"status":\s*401\b'), "http", 0.9),
        (re.compile(r'"error":\s*"unauthorized"', re.I), "http", 0.9),
        (re.compile(r'"error":\s*"authentication_required"', re.I), "http", 0.95),
        (re.compile(r"401 Unauthorized", re.I), "http", 0.9),
        (re.compile(r"WWW-Authenticate:", re.I), "http", 0.85),

        # ── GitHub CLI ────────────────────────────────────────────
        (re.compile(r"gh auth login", re.I), "gh", 0.95),
        (re.compile(r"try authenticating with:\s*gh auth login", re.I), "gh", 0.95),
        (re.compile(r"To use GitHub CLI.*authenticate", re.I), "gh", 0.9),

        # ── Git ───────────────────────────────────────────────────
        (re.compile(r"fatal: Authentication failed", re.I), "git", 0.95),
        (re.compile(r"remote:.*Invalid username or password", re.I), "git", 0.95),
        (re.compile(r"fatal:.*could not read Username", re.I), "git", 0.9),
        (re.compile(r"Could not read from remote repository", re.I), "git", 0.7),

        # ── npm ───────────────────────────────────────────────────
        (re.compile(r"npm ERR! 401 Unauthorized", re.I), "npm", 0.95),
        (re.compile(r"npm ERR! code E401", re.I), "npm", 0.95),
        (re.compile(r"npm ERR! code E403", re.I), "npm", 0.8),

        # ── Docker ────────────────────────────────────────────────
        (re.compile(r"unauthorized: authentication required", re.I), "docker", 0.95),
        (re.compile(r"denied: requested access to the resource is denied", re.I), "docker", 0.9),

        # ── SSH ───────────────────────────────────────────────────
        (re.compile(r"Permission denied \(publickey", re.I), "ssh", 0.9),

        # ── Generic (lower confidence) ────────────────────────────
        (re.compile(r"Login required", re.I), "generic", 0.6),
        (re.compile(r"Authentication required", re.I), "generic", 0.7),
        (re.compile(r"Invalid credentials", re.I), "generic", 0.7),
        (re.compile(r"Access denied", re.I), "generic", 0.5),
    ]

    # Domain extraction helpers
    _URL_RE = re.compile(r"https?://([a-zA-Z0-9][a-zA-Z0-9._-]+)")
    _GIT_REMOTE_RE = re.compile(
        r"git\s+(?:clone|push|pull|fetch)\s+\S*?"
        r"(?:https?://)?([a-zA-Z0-9][a-zA-Z0-9._-]+)",
    )
    _DOCKER_REGISTRY_RE = re.compile(
        r"docker\s+(?:login|pull|push)\s+([a-zA-Z0-9][a-zA-Z0-9._-]+)",
    )

    _TOOL_FROM_CMD: dict[str, str] = {
        "curl": "http", "wget": "http",
        "gh": "gh",
        "git": "git",
        "npm": "npm", "npx": "npm", "yarn": "npm",
        "docker": "docker",
        "ssh": "ssh", "scp": "ssh", "sftp": "ssh",
        "gws": "gws",
    }

    @classmethod
    def detect(
        cls,
        stdout: str,
        stderr: str,
        exit_code: int,
        command: str = "",
    ) -> dict[str, Any] | None:
        """Detect authentication failure in bash output.

        Args:
            stdout: Command stdout.
            stderr: Command stderr.
            exit_code: Process exit code (0 → skip detection).
            command: The original bash command string.

        Returns:
            Dict with keys ``detected``, ``domain``, ``tool``,
            ``confidence``, ``pattern`` — or ``None`` if no auth
            failure detected.
        """
        if exit_code == 0:
            return None

        combined = stdout + "\n" + stderr
        best: dict[str, Any] | None = None
        best_conf = 0.0

        for pattern, tool, confidence in cls._PATTERNS:
            m = pattern.search(combined)
            if m and confidence > best_conf:
                best_conf = confidence
                best = {
                    "detected": True,
                    "tool": tool,
                    "confidence": confidence,
                    "pattern": m.group(0),
                    "domain": None,
                }

        if best is None:
            return None

        # Upgrade generic tool type from command prefix
        if best["tool"] == "generic":
            cmd_tool = cls._tool_from_command(command)
            if cmd_tool:
                best["tool"] = cmd_tool

        best["domain"] = cls.extract_domain_from_command(command)
        return best

    @classmethod
    def extract_domain_from_command(cls, command: str) -> str | None:
        """Extract the target domain from a bash command string.

        Handles: curl/wget URLs, git remote URLs, docker registries,
        and ``gh`` (always github.com).
        """
        stripped = command.strip()
        if not stripped:
            return None

        # gh always targets GitHub
        first_word = stripped.split()[0]
        if first_word == "gh":
            return "github.com"

        # git remote URL
        m = cls._GIT_REMOTE_RE.search(stripped)
        if m:
            return m.group(1).lower()

        # docker registry
        m = cls._DOCKER_REGISTRY_RE.search(stripped)
        if m:
            return m.group(1).lower()

        # Generic URL
        m = cls._URL_RE.search(stripped)
        if m:
            return m.group(1).lower()

        return None

    @classmethod
    def _tool_from_command(cls, command: str) -> str | None:
        """Infer tool type from the first word of the command."""
        stripped = command.strip()
        if not stripped:
            return None
        first = stripped.split()[0]
        return cls._TOOL_FROM_CMD.get(first)
