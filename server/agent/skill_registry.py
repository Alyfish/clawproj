"""
ClawBot Skill Registry

Thread-safe runtime registry that the agentic loop uses to:
- Get skill summaries for the system prompt (cheap, every turn)
- Load full skill content when the LLM activates a skill (expensive, on demand)
- Add dynamically created skills at runtime
- Provide the "load_skill" tool definition for the LLM

Progressive disclosure:
- get_summaries() → ~50 tokens per skill (name + one-liner)
- get_skill_content() → 500-2000 tokens (full SKILL.md body)

The loop injects summaries every turn. Full content only when LLM calls load_skill.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from server.agent.skill_loader import Skill, SkillLoader, SkillSummary

logger = logging.getLogger(__name__)


# ============================================================
# SKILL REGISTRY
# ============================================================


class SkillRegistry:
    """
    Thread-safe registry of available skills.

    Usage:
        loader = SkillLoader("skills/")
        registry = SkillRegistry(loader)

        # Every agentic loop turn:
        system_prompt += registry.get_summaries()

        # When LLM calls load_skill:
        content = registry.get_skill_content("flight-search")
    """

    def __init__(self, loader: SkillLoader) -> None:
        self._loader = loader
        self._lock = threading.RLock()
        self._skills: dict[str, Skill] = {}
        self._load_initial()

    def _load_initial(self) -> None:
        """Load all skills from the loader on initialization."""
        with self._lock:
            skills = self._loader.load_all()
            self._skills = {s.name: s for s in skills}
            logger.info(
                "Registry initialized with %d skill(s): %s",
                len(self._skills),
                ", ".join(sorted(self._skills.keys())) or "(none)",
            )

    # --------------------------------------------------------
    # SYSTEM PROMPT INJECTION (called every turn)
    # --------------------------------------------------------

    def get_summaries(self) -> str:
        """
        Returns a formatted string of all enabled skill summaries,
        ready to inject into the system prompt.

        Format:
            <available_skills>
            - flight-search: Search for flights, compare prices, rank results.
            - apartment-search: Find apartments, detect red flags, draft applications.
            </available_skills>

        Cost: ~50 tokens per skill. Safe to call every turn.
        """
        with self._lock:
            enabled = [s for s in self._skills.values() if s.enabled]

        if not enabled:
            return "<available_skills>\nNo skills loaded.\n</available_skills>"

        lines = [s.summary for s in sorted(enabled, key=lambda s: s.name)]
        body = "\n".join(lines)
        return f"<available_skills>\n{body}\n</available_skills>"

    # --------------------------------------------------------
    # SKILL CONTENT (called on demand when LLM activates a skill)
    # --------------------------------------------------------

    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name. Returns None if not found."""
        with self._lock:
            return self._skills.get(name)

    def get_skill_content(self, name: str) -> Optional[str]:
        """
        Returns the full SKILL.md markdown body for a skill.

        This is the expensive call — potentially 500-2000 tokens.
        Only called when the LLM explicitly decides to use a skill.

        Returns:
            Formatted skill content string, or None if skill not found.
        """
        with self._lock:
            skill = self._skills.get(name)

        if skill is None:
            logger.warning("Skill not found: %s", name)
            return None

        if not skill.enabled:
            logger.warning("Skill is disabled: %s", name)
            return None

        # Build the content block with metadata header
        parts = [
            f'<skill name="{skill.name}">',
            f"Description: {skill.description}",
        ]

        if skill.tools:
            parts.append(f"Tools used: {', '.join(skill.tools)}")

        if skill.approval_actions:
            parts.append(
                f"Actions requiring approval: {', '.join(skill.approval_actions)}"
            )

        parts.append("")  # blank line before content
        parts.append(skill.content)
        parts.append("</skill>")

        return "\n".join(parts)

    # --------------------------------------------------------
    # LISTING
    # --------------------------------------------------------

    def list_skills(self) -> list[SkillSummary]:
        """List all loaded skills as lightweight summaries."""
        with self._lock:
            return [
                SkillSummary(
                    name=s.name,
                    description=s.description,
                    path=s.path,
                )
                for s in sorted(self._skills.values(), key=lambda s: s.name)
            ]

    def list_enabled(self) -> list[str]:
        """List names of all enabled skills."""
        with self._lock:
            return sorted(
                s.name for s in self._skills.values() if s.enabled
            )

    @property
    def count(self) -> int:
        """Number of loaded skills."""
        with self._lock:
            return len(self._skills)

    # --------------------------------------------------------
    # DYNAMIC SKILL MANAGEMENT
    # --------------------------------------------------------

    def add_skill(self, skill: Skill) -> None:
        """
        Add a dynamically created skill (e.g., from the Skill Creator).
        Overwrites any existing skill with the same name.
        """
        with self._lock:
            self._skills[skill.name] = skill
            logger.info("Added skill: %s", skill.name)

    def remove_skill(self, name: str) -> bool:
        """Remove a skill by name. Returns True if removed."""
        with self._lock:
            if name in self._skills:
                del self._skills[name]
                logger.info("Removed skill: %s", name)
                return True
            return False

    def enable_skill(self, name: str) -> bool:
        """Enable a disabled skill. Returns True if found."""
        with self._lock:
            skill = self._skills.get(name)
            if skill:
                skill.enabled = True
                return True
            return False

    def disable_skill(self, name: str) -> bool:
        """Disable a skill (hidden from summaries). Returns True if found."""
        with self._lock:
            skill = self._skills.get(name)
            if skill:
                skill.enabled = False
                return True
            return False

    def reload(self) -> int:
        """
        Re-scan the skills directory and reload all skills.
        Returns the new skill count.
        """
        with self._lock:
            skills = self._loader.reload()
            self._skills = {s.name: s for s in skills}
            logger.info("Reloaded %d skill(s)", len(self._skills))
            return len(self._skills)


# ============================================================
# LOAD_SKILL TOOL DEFINITION
# ============================================================

# This is the tool definition that gets registered with the agentic loop.
# When the LLM calls load_skill, the loop executor uses the registry
# to fetch full skill content and inject it into the conversation.

LOAD_SKILL_TOOL: dict[str, Any] = {
    "name": "load_skill",
    "description": (
        "Load the full instructions for a skill. Call this when you need "
        "detailed guidance on how to perform a task. The available skills "
        "are listed in <available_skills>. Pass the skill name to get "
        "its complete instructions, API details, and examples."
    ),
    "parameters": {
        "skill_name": {
            "type": "string",
            "description": "The name of the skill to load (e.g., 'flight-search')",
            "required": True,
        }
    },
    "requiresApproval": [],
}


def execute_load_skill(
    registry: SkillRegistry, skill_name: str
) -> dict[str, Any]:
    """
    Execute the load_skill tool call.

    Called by the agentic loop when the LLM invokes load_skill.

    Returns:
        ToolResult-compatible dict with the skill content or error.
    """
    content = registry.get_skill_content(skill_name)

    if content is None:
        available = registry.list_enabled()
        return {
            "success": False,
            "error": f"Skill '{skill_name}' not found. Available skills: {', '.join(available)}",
            "output": None,
        }

    return {
        "success": True,
        "output": content,
        "error": None,
    }
