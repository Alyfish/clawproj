"""
ClawBot Skill Loader

Reads SKILL.md files from the filesystem, parses YAML frontmatter
and markdown body, and produces Skill dataclass instances.

SKILL.md format:
    ---
    name: flight-search
    description: Search for flights, compare prices, rank results.
    tools: [http_request, code_execution, create_card]
    approvalActions: [pay, submit]
    version: 1.0.0
    author: clawbot
    ---
    # Context
    You are helping the user find flights...

Aligns with shared/types/skills.ts SkillManifest interface.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class Skill:
    """A parsed skill from a SKILL.md file.

    Fields align with the TypeScript SkillManifest interface
    in shared/types/skills.ts (the source of truth).
    """

    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    approval_actions: list[str] = field(default_factory=list)
    content: str = ""  # markdown body below frontmatter
    path: str = ""  # filesystem path to SKILL.md
    version: str = "0.0.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    enabled: bool = True
    _supplementary_files: Optional[dict[str, str]] = field(
        default=None, repr=False
    )

    @property
    def supplementary_files(self) -> dict[str, str]:
        """Lazily load supplementary files from the skill directory."""
        if self._supplementary_files is None:
            self._supplementary_files = _load_supplementary_files(self.path)
        return self._supplementary_files

    @property
    def summary(self) -> str:
        """One-line summary for system prompt injection."""
        return f"- {self.name}: {self.description}"


@dataclass
class SkillSummary:
    """Lightweight skill reference for listings and system prompt.

    Matches the TypeScript SkillSummary interface in shared/types/skills.ts.
    """

    name: str
    description: str
    path: str


# ============================================================
# FRONTMATTER PARSING
# ============================================================

def parse_skill_file(filepath: str | Path) -> Skill:
    """Parse a SKILL.md file into a Skill dataclass.

    Handles:
    - Standard YAML frontmatter between --- markers
    - Missing or partial frontmatter (uses defaults)
    - Empty content body
    - Malformed YAML (logs warning, uses defaults)

    Args:
        filepath: Path to the SKILL.md file

    Returns:
        Parsed Skill instance

    Raises:
        FileNotFoundError: if filepath doesn't exist
    """
    filepath = Path(filepath)

    if not filepath.exists():
        raise FileNotFoundError(f"Skill file not found: {filepath}")

    raw = filepath.read_text(encoding="utf-8")
    frontmatter, content = _split_frontmatter(raw)
    meta = _parse_yaml(frontmatter, filepath)

    # Accept both camelCase (approvalActions) and snake_case (approval_actions)
    approval_actions = meta.get("approval_actions") or meta.get("approvalActions", [])

    return Skill(
        name=meta.get("name", filepath.parent.name),
        description=meta.get("description", ""),
        tools=_ensure_list(meta.get("tools", [])),
        approval_actions=_ensure_list(approval_actions),
        content=content.strip(),
        path=str(filepath),
        version=str(meta.get("version", "0.0.0")),
        author=str(meta.get("author", "")),
        tags=_ensure_list(meta.get("tags", [])),
        dependencies=_ensure_list(meta.get("dependencies", [])),
        enabled=bool(meta.get("enabled", True)),
    )


def _split_frontmatter(raw: str) -> tuple[str, str]:
    """Split a SKILL.md file into YAML frontmatter and markdown body.

    Expects the format:
        ---
        key: value
        ---
        # Markdown body

    Returns:
        (frontmatter_string, body_string)
        If no frontmatter found, returns ("", full_content)
    """
    stripped = raw.strip()

    # Must start with ---
    if not stripped.startswith("---"):
        return "", raw

    # Find the closing ---
    second_marker = stripped.find("---", 3)
    if second_marker == -1:
        logger.warning("SKILL.md has opening --- but no closing ---")
        return "", raw

    frontmatter = stripped[3:second_marker].strip()
    body = stripped[second_marker + 3:]

    return frontmatter, body


def _parse_yaml(frontmatter: str, filepath: Path) -> dict:
    """Parse YAML frontmatter string, returning empty dict on failure."""
    if not frontmatter:
        return {}

    try:
        parsed = yaml.safe_load(frontmatter)
        if not isinstance(parsed, dict):
            logger.warning(
                "Frontmatter in %s is not a mapping, got %s",
                filepath,
                type(parsed).__name__,
            )
            return {}
        return parsed
    except yaml.YAMLError as e:
        logger.warning("Malformed YAML in %s: %s", filepath, e)
        return {}


def _ensure_list(value: object) -> list[str]:
    """Coerce a value to a list of strings. Handles str, list, None."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


# ============================================================
# SUPPLEMENTARY FILE LOADING
# ============================================================

# Extensions to scan in a skill directory (besides SKILL.md itself)
_SUPPLEMENTARY_EXTENSIONS = {".md", ".json", ".txt", ".yaml", ".yml", ".csv"}


def _load_supplementary_files(skill_md_path: str) -> dict[str, str]:
    """Load other text files from the skill's directory.

    Skips the SKILL.md itself and binary files.

    Returns:
        dict of filename -> content
    """
    result: dict[str, str] = {}
    skill_dir = Path(skill_md_path).parent

    if not skill_dir.is_dir():
        return result

    for item in skill_dir.iterdir():
        if not item.is_file():
            continue
        if item.name.upper() == "SKILL.MD":
            continue
        if item.suffix.lower() not in _SUPPLEMENTARY_EXTENSIONS:
            continue
        try:
            result[item.name] = item.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("Could not read supplementary file %s: %s", item, e)

    return result


# ============================================================
# SKILL LOADER CLASS
# ============================================================

class SkillLoader:
    """Scans a skills directory and loads all SKILL.md files.

    Directory structure expected:
        skills/
            flight-search/
                SKILL.md
                api-reference.md     (optional supplementary)
            apartment-search/
                SKILL.md
            betting-odds/
                SKILL.md
                odds-sources.json    (optional supplementary)
    """

    def __init__(self, skills_dir: str = "skills/") -> None:
        self.skills_dir = Path(skills_dir)
        self._skills: list[Skill] = []
        self._loaded = False

    @property
    def skills(self) -> list[Skill]:
        """All loaded skills. Auto-loads on first access."""
        if not self._loaded:
            self.load_all()
        return self._skills

    def load_all(self) -> list[Skill]:
        """Scan the skills directory and parse all SKILL.md files.

        Returns:
            List of successfully parsed Skills.
            Logs warnings for directories that fail to parse.
        """
        self._skills = []

        if not self.skills_dir.exists():
            logger.info("Skills directory does not exist: %s", self.skills_dir)
            self._loaded = True
            return self._skills

        if not self.skills_dir.is_dir():
            logger.warning("Skills path is not a directory: %s", self.skills_dir)
            self._loaded = True
            return self._skills

        for entry in sorted(self.skills_dir.iterdir()):
            if not entry.is_dir():
                continue

            skill_file = entry / "SKILL.md"
            if not skill_file.exists():
                # Try lowercase
                skill_file = entry / "skill.md"
                if not skill_file.exists():
                    logger.debug("No SKILL.md in %s, skipping", entry.name)
                    continue

            try:
                skill = parse_skill_file(skill_file)
                self._skills.append(skill)
                logger.info("Loaded skill: %s (%s)", skill.name, skill.path)
            except Exception as e:
                logger.warning("Failed to load skill from %s: %s", entry.name, e)

        self._loaded = True
        logger.info(
            "Loaded %d skill(s) from %s", len(self._skills), self.skills_dir
        )
        return self._skills

    def load_skill(self, name: str) -> Optional[Skill]:
        """Load a specific skill by name (directory name).

        Args:
            name: Skill directory name (e.g., "flight-search")

        Returns:
            Parsed Skill or None if not found
        """
        skill_dir = self.skills_dir / name
        skill_file = skill_dir / "SKILL.md"

        if not skill_file.exists():
            skill_file = skill_dir / "skill.md"
            if not skill_file.exists():
                logger.warning("Skill not found: %s", name)
                return None

        try:
            return parse_skill_file(skill_file)
        except Exception as e:
            logger.warning("Failed to load skill %s: %s", name, e)
            return None

    def reload(self) -> list[Skill]:
        """Re-scan the skills directory.

        Called when new skills are created at runtime
        (e.g., by the Skill Creator meta-skill).
        """
        self._loaded = False
        return self.load_all()
