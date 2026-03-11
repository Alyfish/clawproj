"""Tests for auto-emit cards from bash_execute output (CARDS_JSON: convention)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.agent.agent import Agent
from server.agent.tools.tool_registry import ToolResult


def _make_agent() -> Agent:
    """Create a minimal Agent with mocked gateway."""
    agent = Agent.__new__(Agent)
    agent.gateway = MagicMock()
    agent.gateway.emit_card = AsyncMock()
    agent.gateway.emit_task_update = AsyncMock()
    return agent


def _bash_result(stdout: str, success: bool = True) -> ToolResult:
    return ToolResult(
        success=success,
        output={"stdout": stdout, "stderr": "", "exit_code": 0},
    )


@pytest.mark.asyncio
async def test_marker_present_cards_emitted():
    """CARDS_JSON marker → cards emitted, marker stripped from stdout."""
    agent = _make_agent()
    cards = [
        {"type": "flight", "title": "SFO→JFK $199"},
        {"type": "flight", "title": "SFO→JFK $249"},
    ]
    stdout = f"Found 2 flights\nCARDS_JSON:{json.dumps(cards)}"
    result = _bash_result(stdout)

    result = await agent._auto_emit_cards(result, "task-1", "sess-1")

    assert agent.gateway.emit_card.call_count == 2
    assert agent.gateway.emit_task_update.call_count == 2
    # Marker stripped from stdout
    assert "CARDS_JSON" not in result.output["stdout"]
    assert result.output["stdout"] == "Found 2 flights"


@pytest.mark.asyncio
async def test_no_marker_no_cards():
    """No CARDS_JSON marker → no emit_card calls, output unchanged."""
    agent = _make_agent()
    stdout = "total 42\n-rw-r--r-- 1 user staff 100 file.txt"
    result = _bash_result(stdout)

    result = await agent._auto_emit_cards(result, None, "sess-1")

    agent.gateway.emit_card.assert_not_called()
    assert result.output["stdout"] == stdout


@pytest.mark.asyncio
async def test_malformed_json_graceful_skip():
    """CARDS_JSON: with invalid JSON → warning logged, no crash."""
    agent = _make_agent()
    stdout = "some output\nCARDS_JSON:not-valid-json{{"
    result = _bash_result(stdout)

    result = await agent._auto_emit_cards(result, None, "sess-1")

    agent.gateway.emit_card.assert_not_called()
    # Original stdout preserved (unchanged)
    assert result.output["stdout"] == stdout


@pytest.mark.asyncio
async def test_non_list_json_graceful_skip():
    """CARDS_JSON: with a dict instead of list → skipped."""
    agent = _make_agent()
    stdout = f'output\nCARDS_JSON:{json.dumps({"single": "object"})}'
    result = _bash_result(stdout)

    result = await agent._auto_emit_cards(result, None, "sess-1")

    agent.gateway.emit_card.assert_not_called()
    assert result.output["stdout"] == stdout


@pytest.mark.asyncio
async def test_cards_stamped_with_defaults():
    """Cards missing id/source/createdAt get auto-stamped."""
    agent = _make_agent()
    cards = [{"type": "pick", "title": "Jordan 11"}]
    stdout = f"Results:\nCARDS_JSON:{json.dumps(cards)}"
    result = _bash_result(stdout)

    result = await agent._auto_emit_cards(result, None, "sess-1")

    emitted_card = agent.gateway.emit_card.call_args[0][0]
    assert "id" in emitted_card
    assert len(emitted_card["id"]) == 12
    assert emitted_card["source"] == "agent"
    assert "createdAt" in emitted_card
    # Pre-existing fields preserved
    assert emitted_card["type"] == "pick"
    assert emitted_card["title"] == "Jordan 11"
