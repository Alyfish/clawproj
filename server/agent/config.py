"""
ClawBot Agent Configuration

Centralized configuration for the agentic loop. Loaded from environment
variables with sensible defaults. All other modules should import from here
instead of reading os.environ directly.

Env var conventions:
  - ANTHROPIC_API_KEY — Claude API key (standard Anthropic SDK name)
  - CLAWBOT_*        — ClawBot-specific overrides (model, gateway, limits)

Design references:
  - FoundationAgents/OpenManus app/config/config.py (dataclass + env loading)
  - snarktank/ralph (fresh context per iteration, max_iterations safety)
  - Existing ClawBot patterns: CLAWBOT_CRED_*, CLAWBOT_MOCK_SEARCH, CLAWBOT_BROWSER_PORT
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for the ClawBot agent. Loaded from env vars with sensible defaults."""

    # --- Claude API ---
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096
    api_key: str = ""  # loaded from ANTHROPIC_API_KEY

    # --- Agent behavior ---
    max_iterations: int = 25          # safety limit per turn (like Ralph's max_iterations)
    max_tool_retries: int = 2         # retry a failed tool call this many times
    stream_responses: bool = True     # stream text deltas to user in real-time

    # --- Gateway ---
    gateway_url: str = "ws://localhost:8080"
    agent_role: str = "node"
    agent_scopes: list[str] = field(default_factory=lambda: ["agent"])
    reconnect_max_delay: float = 30.0
    reconnect_base_delay: float = 1.0

    # --- Paths (relative to project root) ---
    project_root: str = ""            # auto-detected
    skills_dir: str = "skills/"
    memory_dir: str = "memory/"
    soul_path: str = "SOUL.md"
    credentials_path: str = ".credentials/"

    # --- OpenRouter fallback (cascading, cheapest first) ---
    openrouter_api_key: str = ""      # loaded from OPENROUTER_API_KEY
    openrouter_models: list[str] = field(default_factory=lambda: [
        "google/gemini-2.5-flash-lite",           # ultra cheap, good tool calling
        "google/gemini-2.5-flash",                 # cheap, great quality
        "openai/gpt-4o-mini",                      # cheap, reliable tools
        "meta-llama/llama-3.3-70b-instruct:free",  # free, decent quality
        "anthropic/claude-haiku-4.5",               # cheap Claude
    ])

    # --- Bash-first agent (v2) ---
    searxng_url: str = "http://searxng:8080"    # SearXNG search engine
    workspace_path: str = "/workspace"           # Agent workspace directory
    bash_timeout: int = 30                       # Bash command timeout (seconds)
    bash_max_output: int = 51200                 # Bash output truncation (bytes)

    # --- Test mode ---
    test_mode: bool = False           # stdin/stdout instead of gateway
    mock_tools: bool = False          # use mock tool results

    def __post_init__(self) -> None:
        # Load API key from environment (accept both var names)
        if not self.api_key:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY", "") or os.environ.get("CLAUDE_API_KEY", "")

        # Auto-detect project root (walk up from this file to find SOUL.md)
        if not self.project_root:
            current = Path(__file__).resolve().parent
            while current != current.parent:
                if (current / "SOUL.md").exists():
                    self.project_root = str(current)
                    break
                current = current.parent
            if not self.project_root:
                self.project_root = str(Path(__file__).resolve().parent.parent.parent)

        # Resolve relative paths against project root
        root = Path(self.project_root)
        self.skills_dir = str(root / self.skills_dir)
        self.memory_dir = str(root / self.memory_dir)
        self.soul_path = str(root / self.soul_path)
        self.credentials_path = str(root / self.credentials_path)

        # Load OpenRouter config from environment (accept both var names)
        if not self.openrouter_api_key:
            self.openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "") or os.environ.get("OPEN_ROUTER_API_KEY", "")
        models_env = os.environ.get("OPENROUTER_MODELS") or os.environ.get("OPENROUTER_MODEL")
        if models_env:
            self.openrouter_models = [m.strip() for m in models_env.split(",") if m.strip()]

        # Override from environment
        self.model = os.environ.get("CLAWBOT_MODEL", self.model)
        self.gateway_url = os.environ.get("CLAWBOT_GATEWAY_URL", self.gateway_url)
        self.max_iterations = int(
            os.environ.get("CLAWBOT_MAX_ITERATIONS", str(self.max_iterations))
        )
        test_mode_env = os.environ.get("CLAWBOT_TEST_MODE")
        if test_mode_env is not None:
            self.test_mode = test_mode_env.lower() in ("1", "true", "yes")
        mock_tools_env = os.environ.get("CLAWBOT_MOCK_TOOLS")
        if mock_tools_env is not None:
            self.mock_tools = mock_tools_env.lower() in ("1", "true", "yes")

        # Bash-first agent (v2)
        self.searxng_url = os.environ.get("CLAWBOT_SEARXNG_URL", self.searxng_url)
        self.workspace_path = os.environ.get("CLAWBOT_WORKSPACE", self.workspace_path)
        self.bash_timeout = int(os.environ.get("CLAWBOT_BASH_TIMEOUT", str(self.bash_timeout)))
        self.bash_max_output = int(os.environ.get("CLAWBOT_BASH_MAX_OUTPUT", str(self.bash_max_output)))

    @classmethod
    def from_env(cls) -> AgentConfig:
        """Create config entirely from environment variables."""
        return cls()

    def validate(self) -> list[str]:
        """Return list of validation errors, empty if valid."""
        errors: list[str] = []
        if not self.api_key and not self.test_mode:
            errors.append(
                "ANTHROPIC_API_KEY is required (set env var or pass api_key)"
            )
        if not self.gateway_url and not self.test_mode:
            errors.append("Gateway URL is required")
        if self.max_iterations < 1 or self.max_iterations > 100:
            errors.append(
                f"max_iterations must be 1-100, got {self.max_iterations}"
            )
        return errors
