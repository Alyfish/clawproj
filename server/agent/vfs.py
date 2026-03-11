"""
ClawBot Virtual Filesystem (VFS)

Manages the agent's workspace directory tree. All agent-created files
(memory, scripts, data, skills, logs) live under a single root directory
that maps to a Docker volume at /workspace.

Layout:
    /workspace
    ├── /memory           ← markdown + YAML frontmatter
    │   ├── /profile      ← user identity
    │   ├── /preferences  ← user preferences
    │   ├── /searches     ← past research
    │   └── /general      ← everything else
    ├── /scripts          ← reusable code agent creates
    ├── /data             ← downloads, API responses, temp
    │   └── /cache        ← cached pages
    ├── /skills           ← SKILL.md files
    └── /logs             ← execution logs
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _find_project_root() -> str:
    """Walk up from this file to find the directory containing SOUL.md."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "SOUL.md").exists():
            return str(current)
        current = current.parent
    return str(Path(__file__).resolve().parent.parent.parent)


class VFS:
    """Persistent workspace for the agent."""

    STRUCTURE: dict[str, str] = {
        "memory":             "Persistent agent memory (markdown + YAML frontmatter)",
        "memory/profile":     "User identity and personal info",
        "memory/preferences": "User preferences and settings",
        "memory/searches":    "Past search results and research",
        "memory/general":     "General-purpose memory entries",
        "scripts":            "Reusable code snippets the agent creates",
        "data":               "Downloads, API responses, and temporary files",
        "data/cache":         "Cached web pages and resources",
        "skills":             "SKILL.md runtime skill definitions",
        "logs":               "Agent execution and debug logs",
    }

    def __init__(self, base: str | None = None) -> None:
        if base is None:
            base = os.environ.get("CLAWBOT_WORKSPACE", "")
            if not base:
                if os.path.isdir("/workspace") and os.access("/workspace", os.W_OK):
                    base = "/workspace"
                else:
                    base = os.path.join(_find_project_root(), "workspace")
        self.base: str = os.path.realpath(base)

    def init(self) -> None:
        """Create all workspace directories and write README on first run.

        Idempotent: safe to call multiple times.
        """
        base_path = Path(self.base)

        for rel_path in self.STRUCTURE:
            (base_path / rel_path).mkdir(parents=True, exist_ok=True)

        readme_path = base_path / "README.md"
        if not readme_path.exists():
            readme_path.write_text(self._generate_readme(), encoding="utf-8")
            logger.info("VFS initialized at %s", self.base)
        else:
            logger.debug("VFS already initialized at %s", self.base)

    def sync_skills(self, source_dir: str) -> str:
        """Copy SKILL.md files from source into workspace and generate INDEX.md.

        Scans ``source_dir`` for subdirectories containing a SKILL.md (or
        skill.md) file.  Each matching subdir is copied wholesale into
        ``{self.base}/skills/{name}/`` so the agent can ``cat`` them at
        runtime.  An INDEX.md table is generated for quick lookup.

        Returns:
            Absolute path to the generated INDEX.md.
        """
        src = Path(source_dir)
        dest_skills = Path(self.base) / "skills"
        dest_skills.mkdir(parents=True, exist_ok=True)

        rows: list[dict[str, str]] = []

        if src.is_dir():
            for subdir in sorted(src.iterdir()):
                if not subdir.is_dir():
                    continue
                skill_file = subdir / "SKILL.md"
                if not skill_file.exists():
                    skill_file = subdir / "skill.md"
                if not skill_file.exists():
                    continue

                # Copy entire skill directory
                dest = dest_skills / subdir.name
                shutil.copytree(str(subdir), str(dest), dirs_exist_ok=True)

                # Parse frontmatter
                meta = self._parse_skill_frontmatter(skill_file)
                rows.append({
                    "name": meta.get("name", subdir.name),
                    "description": meta.get("description", ""),
                    "tags": ", ".join(meta.get("tags", [])),
                    "path": f"{self.base}/skills/{subdir.name}/SKILL.md",
                })

        # Generate INDEX.md
        index_path = dest_skills / "INDEX.md"
        index_path.write_text(self._generate_skill_index(rows), encoding="utf-8")
        logger.info("Synced %d skills to %s", len(rows), dest_skills)
        return str(index_path)

    @staticmethod
    def _parse_skill_frontmatter(skill_file: Path) -> dict:
        """Extract YAML frontmatter from a SKILL.md file."""
        try:
            text = skill_file.read_text(encoding="utf-8")
        except OSError:
            return {}
        if not text.startswith("---"):
            return {}
        end = text.find("---", 3)
        if end == -1:
            return {}
        try:
            return yaml.safe_load(text[3:end]) or {}
        except yaml.YAMLError:
            return {}

    def _generate_skill_index(self, rows: list[dict[str, str]]) -> str:
        """Build the INDEX.md content from parsed skill rows."""
        lines = [
            "# Available Skills",
            "",
            "| Skill | Triggers | Path |",
            "|-------|----------|------|",
        ]
        for r in rows:
            lines.append(f"| {r['name']} | {r['tags']} | {r['path']} |")
        lines.extend([
            "",
            "## Usage",
            f"Read a skill before executing: cat {self.base}/skills/{{name}}/SKILL.md",
            "",
        ])
        return "\n".join(lines) + "\n"

    def resolve(self, relative_path: str) -> str:
        """Resolve a relative path within the workspace.

        Returns the absolute resolved path. Raises ValueError if the
        resolved path escapes the workspace (traversal or symlink).
        """
        joined = os.path.join(self.base, relative_path)
        resolved = os.path.realpath(joined)

        if resolved != self.base and not resolved.startswith(self.base + os.sep):
            raise ValueError(
                f"Path traversal blocked: {relative_path!r} resolves to "
                f"{resolved!r} which is outside workspace {self.base!r}"
            )

        return resolved

    def _generate_readme(self) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lines = [
            "# ClawBot Workspace",
            "",
            f"Initialized: {now}",
            "",
            "This directory is the agent's persistent workspace. All agent-created",
            "files are organized into the subdirectories below.",
            "",
            "## Directory Structure",
            "",
            "| Directory | Purpose |",
            "|-----------|---------|",
        ]

        for rel_path, description in self.STRUCTURE.items():
            lines.append(f"| `{rel_path}/` | {description} |")

        lines.extend([
            "",
            "## Notes",
            "",
            "- Memory files use markdown format with YAML frontmatter",
            "- Do not manually modify files while the agent is running",
            "- The `/data/cache` directory may be cleared periodically",
        ])

        return "\n".join(lines) + "\n"
