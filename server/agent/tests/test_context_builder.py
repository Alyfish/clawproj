"""
Tests for ClawBot Context Builder and SOUL.md integration.

Tests verify:
- SOUL.md loads and is included in system prompt
- Skill summaries are injected
- Tool descriptions are formatted correctly
- Memory injection works with mock memory system
- Message building handles all cases
- Context compaction works within token limits
- Fallback behavior when optional systems are missing
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from server.agent.context_builder import (
    ContextBuilder,
    format_tool_descriptions,
)


# ============================================================
# MOCK DEPENDENCIES
# ============================================================

class MockSkillRegistry:
    """Mock SkillRegistry that returns canned summaries."""

    def __init__(self, skills: list[tuple[str, str]] | None = None):
        self._skills = skills or [
            ("flight-search", "Search for flights, compare prices, rank results."),
            ("apartment-search", "Find apartments, detect red flags, draft applications."),
            ("betting-odds", "Analyze sports odds, find value bets, track line movement."),
        ]

    def get_summaries(self) -> str:
        lines = [f"- {name}: {desc}" for name, desc in self._skills]
        return "<available_skills>\n" + "\n".join(lines) + "\n</available_skills>"

    def get_skill_content(self, name: str) -> str | None:
        for sname, desc in self._skills:
            if sname == name:
                return (
                    f'<skill name="{name}">\n'
                    f"Description: {desc}\n\n"
                    f"# Instructions\nDo the {name} thing step by step.\n"
                    f"</skill>"
                )
        return None


class MockMemorySystem:
    """Mock MemorySystem that returns canned search results."""

    def __init__(self, results: list[dict] | None = None):
        self._results = results or [
            {
                "key": "user-profile",
                "content": "Name: Alex. Lives in San Francisco. Prefers window seats.",
                "relevance_score": 0.9,
            },
            {
                "key": "flight-preferences",
                "content": "Prefers United MileagePlus. Budget: $500-800.",
                "relevance_score": 0.7,
            },
        ]

    def search(self, query: str, limit: int = 5) -> list[dict]:
        return self._results[:limit]


class MockMemorySystemError:
    """Mock MemorySystem that raises on search."""
    def search(self, query: str, limit: int = 5) -> list[dict]:
        raise ConnectionError("Memory store unavailable")


# ============================================================
# MOCK TOOLS
# ============================================================

MOCK_TOOLS: list[dict[str, Any]] = [
    {
        "name": "http_request",
        "description": "Make HTTP requests to any API endpoint.",
        "parameters": {
            "method": {"type": "string", "required": True, "description": "HTTP method"},
            "url": {"type": "string", "required": True, "description": "Request URL"},
            "headers": {"type": "object", "required": False, "description": "HTTP headers"},
            "body": {"type": "object", "required": False, "description": "Request body"},
        },
    },
    {
        "name": "browser",
        "description": "Automate browser interactions.",
        "parameters": {
            "action": {"type": "string", "required": True, "description": "Action to perform"},
            "url": {"type": "string", "required": False, "description": "Target URL"},
        },
    },
    {
        "name": "code_execution",
        "description": "Run Python or JavaScript code in a sandbox.",
        "parameters": {
            "language": {"type": "string", "required": True, "description": "python or javascript"},
            "code": {"type": "string", "required": True, "description": "Code to execute"},
        },
    },
]


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def soul_file(tmp_path):
    """Create a test SOUL.md file."""
    soul = tmp_path / "SOUL.md"
    soul.write_text(
        "# ClawBot\n\n"
        "## Identity\n"
        "You are ClawBot, a personal AI agent.\n\n"
        "## Safety Rules\n"
        "Always request approval before payments.\n"
    )
    return soul


@pytest.fixture
def real_soul():
    """Path to the real SOUL.md in the repo root."""
    path = Path("SOUL.md")
    if not path.exists():
        pytest.skip("SOUL.md not found in repo root")
    return path


@pytest.fixture
def builder(soul_file):
    """ContextBuilder with mock dependencies."""
    return ContextBuilder(
        soul_path=str(soul_file),
        skill_registry=MockSkillRegistry(),
        memory_system=MockMemorySystem(),
        tools=MOCK_TOOLS,
        user_timezone="America/Los_Angeles",
    )


@pytest.fixture
def minimal_builder(soul_file):
    """ContextBuilder with no optional dependencies."""
    return ContextBuilder(soul_path=str(soul_file))


# ============================================================
# TESTS: SOUL.MD LOADING
# ============================================================

class TestSoulLoading:
    def test_loads_soul_file(self, builder):
        prompt = builder.build_system_prompt()
        assert "ClawBot" in prompt
        assert "Safety Rules" in prompt

    def test_fallback_on_missing_soul(self, tmp_path):
        builder = ContextBuilder(soul_path=str(tmp_path / "missing.md"))
        prompt = builder.build_system_prompt()
        assert "ClawBot" in prompt  # fallback mentions ClawBot
        assert "approval" in prompt  # fallback mentions safety

    def test_real_soul_loads(self, real_soul):
        builder = ContextBuilder(soul_path=str(real_soul))
        prompt = builder.build_system_prompt()
        assert "ClawBot" in prompt
        assert "Safety" in prompt or "safety" in prompt
        # Should be substantial
        assert len(prompt) > 500

    def test_reload_soul(self, soul_file):
        builder = ContextBuilder(soul_path=str(soul_file))
        original = builder.build_system_prompt()

        # Modify the file
        soul_file.write_text("# Updated\nNew content.")
        builder.reload_soul()
        updated = builder.build_system_prompt()

        assert "Updated" in updated
        assert original != updated


# ============================================================
# TESTS: SYSTEM PROMPT ASSEMBLY
# ============================================================

class TestSystemPrompt:
    def test_contains_all_sections(self, builder):
        prompt = builder.build_system_prompt(memory_query="flights")
        # SOUL
        assert "ClawBot" in prompt
        # Skills — no longer inline (progressive loading), so no <available_skills>
        assert "<available_skills>" not in prompt
        # Tools
        assert "http_request" in prompt
        assert "browser" in prompt
        assert "<available_tools>" in prompt
        # Context
        assert "<current_context>" in prompt
        assert "Current date:" in prompt
        assert "America/Los_Angeles" in prompt
        # Memory
        assert "<relevant_memory>" in prompt
        assert "user-profile" in prompt

    def test_section_order(self, builder):
        prompt = builder.build_system_prompt(memory_query="test")
        # SOUL should come before tools
        soul_pos = prompt.find("ClawBot")
        tools_pos = prompt.find("<available_tools>")
        context_pos = prompt.find("<current_context>")
        memory_pos = prompt.find("<relevant_memory>")
        assert soul_pos < tools_pos < context_pos < memory_pos

    def test_no_memory_without_query(self, builder):
        prompt = builder.build_system_prompt()  # no memory_query
        assert "<relevant_memory>" not in prompt

    def test_no_skills_without_registry(self, minimal_builder):
        prompt = minimal_builder.build_system_prompt()
        assert "<available_skills>" not in prompt
        assert "<skills_index>" not in prompt
        assert "ClawBot" in prompt  # SOUL still present

    def test_no_tools_without_tools(self, minimal_builder):
        prompt = minimal_builder.build_system_prompt()
        assert "<available_tools>" not in prompt

    def test_memory_error_handled_gracefully(self, soul_file):
        builder = ContextBuilder(
            soul_path=str(soul_file),
            memory_system=MockMemorySystemError(),
        )
        # Should not crash
        prompt = builder.build_system_prompt(memory_query="test")
        assert "<relevant_memory>" not in prompt

    def test_memory_low_relevance_filtered(self, soul_file):
        low_results = MockMemorySystem(results=[
            {"key": "irrelevant", "content": "Junk", "relevance_score": 0.05},
        ])
        builder = ContextBuilder(
            soul_path=str(soul_file),
            memory_system=low_results,
        )
        prompt = builder.build_system_prompt(memory_query="test")
        assert "irrelevant" not in prompt


# ============================================================
# TESTS: TOOL DESCRIPTION FORMATTING
# ============================================================

class TestFormatToolDescriptions:
    def test_formats_tools(self):
        output = format_tool_descriptions(MOCK_TOOLS)
        assert "http_request:" in output
        assert "browser:" in output
        assert "code_execution:" in output
        assert "method (string, required)" in output
        assert "url (string, required)" in output
        assert "headers (object)" in output  # not required, no suffix

    def test_empty_tools(self):
        assert format_tool_descriptions([]) == "No tools available."

    def test_tool_with_no_params(self):
        output = format_tool_descriptions([
            {"name": "noop", "description": "Does nothing.", "parameters": {}},
        ])
        assert "noop: Does nothing." in output
        assert "Params: none" in output


# ============================================================
# TESTS: MESSAGE BUILDING
# ============================================================

class TestBuildMessages:
    def test_simple_message(self, builder):
        messages = builder.build_messages(
            session_history=[],
            user_message="Find flights to London",
        )
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Find flights to London"

    def test_with_history(self, builder):
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ]
        messages = builder.build_messages(
            session_history=history,
            user_message="Find flights",
        )
        assert len(messages) == 3
        assert messages[0]["content"] == "Hello"
        assert messages[-1]["content"] == "Find flights"

    def test_with_injected_skill(self, builder):
        messages = builder.build_messages(
            session_history=[],
            user_message="Find flights to London",
            injected_skill="Full skill content here...",
            injected_skill_name="flight-search",
        )
        # Should have: skill injection + assistant ack + user message = 3
        assert len(messages) == 3
        assert "flight-search" in messages[0]["content"]
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["content"] == "Find flights to London"

    def test_history_not_mutated(self, builder):
        history = [{"role": "user", "content": "Hello"}]
        original_len = len(history)
        builder.build_messages(session_history=history, user_message="Test")
        assert len(history) == original_len  # should not modify original


# ============================================================
# TESTS: CONTEXT COMPACTION
# ============================================================

class TestCompactHistory:
    def test_no_compaction_needed(self, builder):
        messages = [{"role": "user", "content": "Short message"}]
        result = builder.compact_history(messages)
        assert result == messages

    def test_compaction_removes_older(self, soul_file):
        builder = ContextBuilder(
            soul_path=str(soul_file),
            max_tokens=100,  # very low threshold
            keep_recent=3,
        )
        messages = [
            {"role": "user", "content": f"Message {i}" + " padding" * 50}
            for i in range(10)
        ]
        result = builder.compact_history(messages)
        # Should be significantly fewer messages
        assert len(result) < len(messages)
        # Last message should be preserved
        assert "Message 9" in result[-1]["content"]

    def test_compaction_preserves_recent(self, soul_file):
        builder = ContextBuilder(
            soul_path=str(soul_file),
            max_tokens=50,
            keep_recent=5,
        )
        messages = [
            {"role": "user", "content": f"Old message {i}" + " x" * 100}
            for i in range(20)
        ]
        result = builder.compact_history(messages)
        # The summary message should mention old content
        assert "Summary" in result[0]["content"]

    def test_compaction_tiny_history(self, soul_file):
        builder = ContextBuilder(
            soul_path=str(soul_file),
            max_tokens=10,
            keep_recent=50,  # more than messages
        )
        messages = [
            {"role": "user", "content": "Short"},
        ]
        # Can't compact below message count — returns as-is
        result = builder.compact_history(messages)
        assert len(result) == 1


# ============================================================
# TESTS: TOKEN ESTIMATION
# ============================================================

class TestTokenEstimation:
    def test_estimate_tokens(self):
        assert ContextBuilder.estimate_tokens("") == 0
        # ~4 chars per token
        assert ContextBuilder.estimate_tokens("a" * 400) == 100
        # English text
        text = "Hello, how are you doing today?"
        tokens = ContextBuilder.estimate_tokens(text)
        assert 5 <= tokens <= 15  # rough sanity check


# ============================================================
# TESTS: CONFIGURATION
# ============================================================

class TestConfiguration:
    def test_set_timezone(self, builder):
        builder.set_user_timezone("Europe/London")
        prompt = builder.build_system_prompt()
        assert "Europe/London" in prompt

    def test_set_tools(self, builder):
        builder.set_tools([{"name": "new_tool", "description": "New.", "parameters": {}}])
        prompt = builder.build_system_prompt()
        assert "new_tool" in prompt
        assert "http_request" not in prompt  # replaced


# ============================================================
# FIXTURE: BUILDER WITH WORKSPACE
# ============================================================

@pytest.fixture
def builder_with_workspace(soul_file, tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "data").mkdir()
    (ws / "logs").mkdir()
    (ws / "skills").mkdir()
    return ContextBuilder(
        soul_path=str(soul_file),
        skill_registry=MockSkillRegistry(),
        memory_system=MockMemorySystem(),
        tools=MOCK_TOOLS,
        workspace_path=str(ws),
    )


# ============================================================
# TESTS: PROGRESSIVE SKILL LOADING
# ============================================================

class TestProgressiveSkillLoading:
    def test_skills_not_in_base_prompt(self, builder_with_workspace):
        prompt = builder_with_workspace.build_system_prompt()
        assert "<available_skills>" not in prompt
        assert "flight-search" not in prompt  # full skill content not inlined
        assert "apartment-search" not in prompt

    def test_skill_reference_in_prompt(self, builder_with_workspace):
        prompt = builder_with_workspace.build_system_prompt()
        assert "INDEX.md" in prompt
        assert "<skills_index>" in prompt


# ============================================================
# TESTS: COMPACTION UPGRADE
# ============================================================

class TestCompactionUpgrade:
    def test_compaction_triggers_at_120k(self, soul_file):
        builder = ContextBuilder(
            soul_path=str(soul_file),
            max_tokens=120_000,
            keep_recent=5,
        )
        # Create messages totalling ~130K tokens (~520K chars)
        messages = [
            {"role": "user", "content": "x" * 26_000}
            for _ in range(20)
        ]
        result = builder.compact_history(messages)
        assert len(result) < len(messages)

    def test_compaction_saves_log(self, builder_with_workspace, tmp_path):
        builder_with_workspace._max_tokens = 50
        builder_with_workspace._keep_recent = 3
        messages = [
            {"role": "user", "content": f"Message {i}" + " pad" * 50}
            for i in range(10)
        ]
        builder_with_workspace.compact_history(messages)
        logs_dir = tmp_path / "workspace" / "logs"
        log_files = list(logs_dir.glob("session-*.md"))
        assert len(log_files) >= 1
        content = log_files[0].read_text()
        assert "Conversation Log" in content

    def test_compaction_keeps_recent(self, soul_file):
        builder = ContextBuilder(
            soul_path=str(soul_file),
            max_tokens=10,
            keep_recent=15,
        )
        messages = [
            {"role": "user", "content": f"Message {i}" + " x" * 100}
            for i in range(30)
        ]
        result = builder.compact_history(messages)
        # Last message should be preserved
        assert "Message 29" in result[-1]["content"]

    def test_compaction_has_summary(self, builder_with_workspace):
        builder_with_workspace._max_tokens = 50
        builder_with_workspace._keep_recent = 3
        messages = [
            {"role": "user", "content": f"Message {i}" + " pad" * 50}
            for i in range(10)
        ]
        result = builder_with_workspace.compact_history(messages)
        assert "Summary" in result[0]["content"]


# ============================================================
# TESTS: TOOL RESULT OFFLOADING
# ============================================================

class TestToolResultOffloading:
    def test_large_tool_result_offloaded(self, builder_with_workspace, tmp_path):
        big_result = "x" * 10_000
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "test-123",
                        "content": big_result,
                    }
                ],
            }
        ]
        builder_with_workspace._offload_large_tool_results(messages)
        part = messages[0]["content"][0]
        assert "Output saved to" in part["content"]
        assert "10000 chars" in part["content"]
        # File should exist
        data_dir = tmp_path / "workspace" / "data"
        files = list(data_dir.glob("tool-result-*.json"))
        assert len(files) == 1
        assert files[0].read_text() == big_result

    def test_small_tool_result_kept(self, builder_with_workspace):
        small_result = "small output"
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "test-456",
                        "content": small_result,
                    }
                ],
            }
        ]
        builder_with_workspace._offload_large_tool_results(messages)
        assert messages[0]["content"][0]["content"] == small_result
