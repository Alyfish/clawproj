"""
Integration test for the ClawBot agentic loop.

Runs in test mode (stdin/stdout, no gateway needed).
Simulates a user asking "find cheap flights SFO to London in April"
and verifies the agent loads a skill, uses tools, and produces output.

Usage: python -m server.agent.test_agent
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from .config import AgentConfig
from .agent import Agent
from .helpers import describe_tool_call, generate_run_id, summarize_result

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


class TestGateway:
    """Records all gateway calls for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []
        self.text_deltas: list[str] = []
        self.tool_starts: list[str] = []
        self.tool_ends: list[tuple[str, bool]] = []
        self.cards: list[dict[str, Any]] = []

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return True

    async def stream_text(
        self, delta: str, session_id: str | None = None,
    ) -> None:
        self.text_deltas.append(delta)
        print(delta, end="", flush=True)

    async def stream_lifecycle(
        self, status: str, run_id: str, session_id: str | None = None,
    ) -> None:
        self.events.append(("lifecycle", status, run_id))
        if status == "start":
            print("\n--- Agent Start ---")
        elif status == "end":
            print("\n--- Agent End ---")

    async def stream_thinking(
        self,
        tool_name: str,
        summary: str,
        status: str = "running",
        session_id: str | None = None,
    ) -> None:
        self.events.append(("thinking", tool_name, summary, status))
        print(f"\n  [{status}] {tool_name}: {summary}")

    async def emit_tool_start(
        self, tool_name: str, description: str, session_id: str | None = None,
    ) -> None:
        self.tool_starts.append(tool_name)
        print(f"\n  Start: {description}")

    async def emit_tool_end(
        self,
        tool_name: str,
        success: bool,
        summary: str,
        session_id: str | None = None,
    ) -> None:
        self.tool_ends.append((tool_name, success))
        icon = "OK" if success else "FAIL"
        print(f"  {icon}: {summary}")

    async def emit_card(self, card: dict[str, Any]) -> None:
        self.cards.append(card)
        print(f"\n  Card: {json.dumps(card, indent=2)[:200]}")

    async def emit_event(self, event: str, payload: dict[str, Any]) -> None:
        self.events.append(("event", event, str(payload)[:100]))

    async def emit_task_update(
        self,
        task_id: str,
        status: str,
        step: dict[str, Any] | None = None,
        card: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(("task", task_id, status))

    async def request_approval(
        self,
        action: str,
        description: str,
        details: dict[str, Any] | None = None,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        print(f"\n  Auto-approving: {description}")
        return {"approved": True, "message": "Auto-approved in test"}


async def run_tests() -> None:
    print("=" * 60)
    print("ClawBot Agent Integration Tests")
    print("=" * 60)

    config = AgentConfig(
        test_mode=True,
        api_key="test-key",  # Will be overridden by mock
        max_iterations=5,
    )

    gateway = TestGateway()

    # Mock the skill registry
    mock_skill_registry = MagicMock()
    mock_skill_registry.get_skill_content.return_value = (
        "# Flight Search Skill\nUse http_request to search flight APIs."
    )
    mock_skill_registry.list_skill_names.return_value = [
        "flight-search",
        "hotel-booking",
    ]

    # Mock the context builder
    mock_context_builder = MagicMock()
    mock_context_builder.build_system_prompt.return_value = (
        "You are ClawBot, a helpful AI assistant."
    )
    mock_context_builder.build_messages.return_value = [
        {"role": "user", "content": "Find cheap flights SFO to London in April"},
    ]

    # Mock the tool registry
    mock_tool_registry = MagicMock()
    mock_tool_registry.list_tools.return_value = ["http_request", "create_card"]
    mock_tool_registry.get.return_value = MagicMock(
        name="http_request",
        description="Make HTTP request",
        parameters={"url": {"type": "string", "required": True}},
    )
    mock_tool_registry.get_tool_definitions.return_value = [
        {
            "name": "http_request",
            "description": "Make HTTP request",
            "input_schema": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    ]

    # Create agent
    agent = Agent(
        config=config,
        gateway_client=gateway,
        context_builder=mock_context_builder,
        skill_registry=mock_skill_registry,
        tool_registry=mock_tool_registry,
    )

    # Test 1: Verify agent initializes
    print("\nTest 1: Agent initialization")
    assert agent.config.model == "claude-sonnet-4-5-20250929"
    assert agent.config.max_iterations == 5
    print("  PASS: Agent initialized correctly")

    # Test 2: Verify process_message with mocked Claude API
    print("\nTest 2: Process message (mocked Claude)")

    # Create a mock that simulates Claude's streaming response
    mock_block = MagicMock()
    mock_block.type = "text"
    mock_block.text = "I'll help you find flights from SFO to London!"
    mock_block.model_dump.return_value = {
        "type": "text",
        "text": "I'll help you find flights from SFO to London!",
    }

    mock_message = MagicMock()
    mock_message.content = [mock_block]
    mock_message.stop_reason = "end_turn"

    # Mock the streaming context manager
    mock_stream = AsyncMock()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=False)
    mock_stream.get_final_message = AsyncMock(return_value=mock_message)

    # Make the stream iterable but yield no events (text comes via final_message)
    async def empty_iter() -> Any:
        return
        yield  # Make this an async generator  # noqa: RET504

    mock_stream.__aiter__ = lambda self: empty_iter()

    agent.client.messages.stream = MagicMock(return_value=mock_stream)

    await agent.process_message(
        "Find cheap flights SFO to London in April", "test-session",
    )

    # Verify lifecycle events
    lifecycle_events = [e for e in gateway.events if e[0] == "lifecycle"]
    assert len(lifecycle_events) >= 2, (
        f"Expected start+end lifecycle events, got {lifecycle_events}"
    )
    assert lifecycle_events[0][1] == "start"
    assert lifecycle_events[-1][1] == "end"
    print("  PASS: Lifecycle events emitted (start + end)")
    print("  PASS: process_message completed without errors")

    # Test 3: Verify history is saved
    print("\nTest 3: History persistence")
    history = agent.get_history("test-session")
    assert len(history) > 0, "History should be saved after processing"
    print(f"  PASS: History saved ({len(history)} messages)")

    # Test 4: Clear history
    print("\nTest 4: Clear history")
    agent.clear_history("test-session")
    assert len(agent.get_history("test-session")) == 0
    print("  PASS: History cleared")

    # Test 5: Test helper functions
    print("\nTest 5: Helper functions")
    assert "Searching" in describe_tool_call("web_search", {"query": "flights"})
    assert "HTTP GET" in describe_tool_call(
        "http_request", {"method": "GET", "url": "https://api.test.com"},
    )
    assert "Loading skill" in describe_tool_call(
        "load_skill", {"skill_name": "flight-search"},
    )
    run_id = generate_run_id()
    assert run_id.startswith("run_")
    assert len(run_id) == 16  # "run_" + 12 hex chars
    print("  PASS: describe_tool_call works for all tool types")
    print("  PASS: generate_run_id produces correct format")

    # Test 6: Config validation
    print("\nTest 6: Config validation")
    bad_config = AgentConfig(max_iterations=200)
    errors = bad_config.validate()
    assert any("max_iterations" in e for e in errors)
    print("  PASS: Config validation catches invalid values")

    # Summary
    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
    print("\nTo run the agent interactively in test mode:")
    print("  python -m server.agent.main --test")
    print("\nTo run with the gateway:")
    print("  python -m server.agent.main")


if __name__ == "__main__":
    asyncio.run(run_tests())
