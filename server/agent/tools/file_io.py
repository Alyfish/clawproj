"""
ClawBot File I/O Tool

Sandboxed file read/write/list/exists operations for the agent.

The agent uses this tool to:
- Read skill files and configuration
- Save processed data and generated content
- Create new skills at runtime (via Skill Creator meta-skill)
- Check file existence before operations

Security model:
- All paths are relative to the project root
- Only ALLOWED_DIRS are accessible (skills, memory, temp)
- Path traversal (../) is blocked via resolved path checking
- Sensitive directories and files are explicitly blocked
- Adapted from claw0/learn-claude-code safe_path() pattern

Design references:
    - claw0 sessions/en/s02_tool_use.py (safe_path validation, workspace restriction)
    - learn-claude-code agents/s02_tool_use.py (path traversal prevention, mkdir -p)
    - OpenManus app/tool/file_operators.py (Protocol-based file operations)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from server.agent.tools.tool_registry import BaseTool, ToolResult, truncate

logger = logging.getLogger(__name__)

# Directories the agent is allowed to access (relative to project root).
ALLOWED_DIRS = {"skills", "memory", "temp"}

# Path components that are always blocked.
BLOCKED_PATTERNS = {".env", ".git", ".ssh", "__pycache__", "node_modules"}

# Top-level paths that are explicitly blocked (source code directories).
_BLOCKED_ROOTS = {"server", "ios", "shared"}

# Individual files that are blocked.
_BLOCKED_FILES = {"SOUL.md"}


class FileIoTool(BaseTool):
    """Sandboxed file I/O for the agent runtime.

    All paths are relative to the project root and restricted
    to ALLOWED_DIRS. The agent cannot access source code,
    environment files, or sensitive configuration.
    """

    def __init__(self, project_root: Optional[str] = None) -> None:
        self._project_root = Path(project_root or ".").resolve()

    @property
    def name(self) -> str:
        return "file_io"

    @property
    def description(self) -> str:
        return (
            "Read and write files on the server. Use for reading "
            "skill files, saving data, or creating new skills."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "description": (
                    "File operation to perform: "
                    "'read', 'write', 'list', or 'exists'"
                ),
                "enum": ["read", "write", "list", "exists"],
            },
            "path": {
                "type": "string",
                "required": True,
                "description": (
                    "File or directory path relative to project root. "
                    "Must be within allowed directories: "
                    + ", ".join(sorted(ALLOWED_DIRS))
                ),
            },
            "content": {
                "type": "string",
                "required": False,
                "description": "File content to write (required for 'write' action)",
            },
        }

    # --------------------------------------------------------
    # PATH VALIDATION
    # --------------------------------------------------------

    def _validate_path(self, path_str: str) -> Path:
        """Validate and resolve a path against security rules.

        Adapted from claw0's safe_path() pattern.

        Args:
            path_str: Relative path string from the LLM.

        Returns:
            Resolved absolute Path.

        Raises:
            ValueError: If the path violates any security rule.
        """
        # Resolve against project root
        resolved = (self._project_root / path_str).resolve()

        # Block path traversal (../ escaping project root)
        if not resolved.is_relative_to(self._project_root):
            raise ValueError(
                f"Path escapes project root: {path_str!r}. "
                f"All paths must be within the project directory."
            )

        # Get the relative path components
        try:
            rel = resolved.relative_to(self._project_root)
        except ValueError:
            raise ValueError(f"Path escapes project root: {path_str!r}")

        parts = rel.parts
        if not parts:
            raise ValueError("Empty path. Specify a file or directory.")

        # Check first component is in ALLOWED_DIRS
        first_component = parts[0]
        if first_component not in ALLOWED_DIRS:
            raise ValueError(
                f"Access denied: {first_component!r} is not an allowed directory. "
                f"Allowed: {', '.join(sorted(ALLOWED_DIRS))}"
            )

        # Check no component matches BLOCKED_PATTERNS
        for part in parts:
            if part in BLOCKED_PATTERNS:
                raise ValueError(
                    f"Access denied: {part!r} is a blocked path component."
                )

        # Block source code directories
        if first_component in _BLOCKED_ROOTS:
            raise ValueError(
                f"Access denied: {first_component!r} is a source code directory."
            )

        # Block individual sensitive files
        if parts[-1] in _BLOCKED_FILES:
            raise ValueError(
                f"Access denied: {parts[-1]!r} is a protected file."
            )

        return resolved

    # --------------------------------------------------------
    # EXECUTE
    # --------------------------------------------------------

    async def execute(
        self,
        action: str = "read",
        path: str = "",
        content: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a file I/O operation.

        Args:
            action: One of "read", "write", "list", "exists"
            path: Relative path within allowed directories
            content: File content for "write" action

        Returns:
            ToolResult with operation-specific output.
        """
        # Validate action
        if action not in ("read", "write", "list", "exists"):
            return self.fail(
                f"Invalid action: {action!r}. "
                f"Use 'read', 'write', 'list', or 'exists'."
            )

        if not path:
            return self.fail("No path provided.")

        # Validate path
        try:
            resolved = self._validate_path(path)
        except ValueError as e:
            return self.fail(str(e))

        # Dispatch to action handler
        try:
            if action == "read":
                return self._read(resolved, path)
            elif action == "write":
                return self._write(resolved, path, content)
            elif action == "list":
                return self._list(resolved, path)
            elif action == "exists":
                return self._exists(resolved)
            else:
                return self.fail(f"Unknown action: {action!r}")
        except Exception as e:
            logger.warning("File I/O error: action=%s path=%s error=%s", action, path, e)
            return self.fail(f"File operation failed: {e}")

    # --------------------------------------------------------
    # ACTION HANDLERS
    # --------------------------------------------------------

    def _read(self, resolved: Path, display_path: str) -> ToolResult:
        """Read a file and return its contents."""
        if not resolved.exists():
            return self.fail(f"File not found: {display_path}")

        if not resolved.is_file():
            return self.fail(f"Not a file: {display_path}")

        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return self.fail(
                f"Cannot read {display_path}: not a text file (binary content)."
            )

        # Truncate large files (shared truncate from claw0)
        content = truncate(content)

        return self.success({
            "content": content,
            "size": resolved.stat().st_size,
            "path": display_path,
        })

    def _write(
        self, resolved: Path, display_path: str, content: Optional[str]
    ) -> ToolResult:
        """Write content to a file."""
        if content is None:
            return self.fail(
                "No content provided. The 'content' parameter is required "
                "for write operations."
            )

        # Create parent directories
        resolved.parent.mkdir(parents=True, exist_ok=True)

        resolved.write_text(content, encoding="utf-8")

        logger.info("Wrote %d bytes to %s", len(content), display_path)

        return self.success({
            "path": display_path,
            "bytes_written": len(content),
        })

    def _list(self, resolved: Path, display_path: str) -> ToolResult:
        """List directory contents (1 level, no recursion)."""
        if not resolved.exists():
            return self.fail(f"Directory not found: {display_path}")

        if not resolved.is_dir():
            return self.fail(f"Not a directory: {display_path}")

        entries = []
        for item in sorted(resolved.iterdir()):
            entries.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            })

        return self.success({
            "path": display_path,
            "entries": entries,
            "count": len(entries),
        })

    def _exists(self, resolved: Path) -> ToolResult:
        """Check if a path exists."""
        return self.success({
            "exists": resolved.exists(),
            "is_file": resolved.is_file() if resolved.exists() else False,
            "is_directory": resolved.is_dir() if resolved.exists() else False,
        })
