"""
ClawBot Agent Module

Core agent infrastructure: skill loading, registry, and agentic loop.
"""

from server.agent.skill_loader import Skill, SkillLoader, SkillSummary
from server.agent.skill_registry import (
    LOAD_SKILL_TOOL,
    SkillRegistry,
    execute_load_skill,
)
from server.agent.context_builder import ContextBuilder
from server.agent.agent import Agent
from server.agent.config import AgentConfig

__all__ = [
    "Skill",
    "SkillLoader",
    "SkillSummary",
    "SkillRegistry",
    "LOAD_SKILL_TOOL",
    "execute_load_skill",
    "ContextBuilder",
    "Agent",
    "AgentConfig",
]
