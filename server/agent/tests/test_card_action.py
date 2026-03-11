"""
Tests for card action handling.

Covers:
- _card_action_to_message translation (all known action/cardType combos)
- Generic fallback for unknown actions
- _CARD_ACTION_ACK lookup
- Agent._handle_card_action integration (ack + process_message dispatch)
- Agent.run() intercept for card_action messages
"""
from __future__ import annotations

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from server.agent.agent import (
    Agent,
    _card_action_to_message,
    _CARD_ACTION_ACK,
)


# ── Translation tests ──────────────────────────────────────────────


class TestCardActionToMessage:
    """Test the pure translation function."""

    def test_watch_price_flight(self):
        msg = _card_action_to_message("watch_price", "flight", {
            "airline": "Delta",
            "route": "NYC → LAX",
            "price": "450",
        })
        assert "Watch Price" in msg
        assert "flight" in msg
        assert "Delta" in msg
        assert "NYC → LAX" in msg
        assert "$450" in msg
        assert "every 2 hours" in msg
        assert "$20" in msg

    def test_watch_price_house(self):
        msg = _card_action_to_message("watch_price", "house", {
            "address": "123 Main St",
            "rent": "2500",
        })
        assert "Watch Price" in msg
        assert "house" in msg
        assert "123 Main St" in msg
        assert "$2500/month" in msg
        assert "daily" in msg

    def test_watch_line_pick(self):
        msg = _card_action_to_message("watch_line", "pick", {
            "matchup": "Lakers vs Celtics",
            "line": "-3.5",
        })
        assert "Watch Line" in msg
        assert "Lakers vs Celtics" in msg
        assert "-3.5" in msg
        assert "every hour" in msg

    def test_book_flight(self):
        msg = _card_action_to_message("book", "flight", {
            "airline": "United",
            "route": "SFO → JFK",
            "price": "320",
            "url": "https://united.com/book/123",
        })
        assert "Book This" in msg
        assert "United" in msg
        assert "SFO → JFK" in msg
        assert "$320" in msg
        assert "https://united.com/book/123" in msg
        assert "approval" in msg.lower()

    def test_place_bet_pick(self):
        msg = _card_action_to_message("place_bet", "pick", {
            "matchup": "Chiefs vs Bills",
            "line": "+7",
        })
        assert "Place Bet" in msg
        assert "Chiefs vs Bills" in msg
        assert "+7" in msg
        assert "approval" in msg.lower()

    def test_schedule_tour_house(self):
        msg = _card_action_to_message("schedule_tour", "house", {
            "address": "456 Oak Ave",
        })
        assert "Schedule Tour" in msg
        assert "456 Oak Ave" in msg
        assert "approval" in msg.lower()

    def test_save_any_card(self):
        data = {"title": "Test Card", "price": "99"}
        msg = _card_action_to_message("save", "flight", data)
        assert "Save" in msg
        assert "flight" in msg
        assert "memory" in msg.lower()
        # Card data should be JSON-serialized in the message
        assert "Test Card" in msg
        assert "99" in msg

    def test_generic_fallback(self):
        data = {"foo": "bar"}
        msg = _card_action_to_message("custom_action", "custom_type", data)
        assert "custom_action" in msg
        assert "custom_type" in msg
        assert "bar" in msg
        assert "appropriate action" in msg

    def test_missing_card_data_fields(self):
        """Translation works with empty card_data — fields default to empty strings."""
        msg = _card_action_to_message("watch_price", "flight", {})
        assert "Watch Price" in msg
        assert "flight" in msg
        # Empty fields shouldn't crash
        assert "$" in msg

    def test_book_requires_approval_language(self):
        """Book and place_bet messages must include approval language."""
        book_msg = _card_action_to_message("book", "flight", {})
        assert "approval" in book_msg.lower()

        bet_msg = _card_action_to_message("place_bet", "pick", {})
        assert "approval" in bet_msg.lower()

        tour_msg = _card_action_to_message("schedule_tour", "house", {})
        assert "approval" in tour_msg.lower()


# ── ACK dict tests ─────────────────────────────────────────────────


class TestCardActionAck:
    """Test the acknowledgment lookup dict."""

    def test_known_actions_have_ack(self):
        for action in ("watch_price", "watch_line", "book", "place_bet",
                        "schedule_tour", "save"):
            assert action in _CARD_ACTION_ACK
            assert len(_CARD_ACTION_ACK[action]) > 0

    def test_ack_messages_end_with_ellipsis(self):
        for ack in _CARD_ACTION_ACK.values():
            assert ack.endswith("...")


# ── Agent integration tests ────────────────────────────────────────


@pytest.fixture
def mock_agent():
    """Create a minimal Agent with mocked dependencies."""
    config = MagicMock()
    config.model = "claude-test"
    config.max_iterations = 5
    config.max_tokens = 4096

    gateway = AsyncMock()
    gateway.stream_text = AsyncMock()
    gateway.stream_lifecycle = AsyncMock()
    gateway.receive_messages = AsyncMock()

    context_builder = MagicMock()
    skill_registry = MagicMock()
    tool_registry = MagicMock()

    agent = Agent(
        config=config,
        gateway_client=gateway,
        context_builder=context_builder,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    return agent


class TestHandleCardAction:
    """Test Agent._handle_card_action integration."""

    @pytest.mark.asyncio
    async def test_sends_ack_before_processing(self, mock_agent):
        """Acknowledgment text is streamed before process_message is called."""
        mock_agent.process_message = AsyncMock()

        payload = {
            "action": "watch_price",
            "cardType": "flight",
            "cardData": {"airline": "Delta", "route": "NYC → LAX", "price": "450"},
        }
        await mock_agent._handle_card_action(payload, "session-1")

        # Ack streamed first
        mock_agent.gateway.stream_text.assert_called_once()
        ack_text = mock_agent.gateway.stream_text.call_args[0][0]
        assert "price monitoring" in ack_text.lower()

        # Then process_message called with synthetic message
        mock_agent.process_message.assert_called_once()
        synthetic = mock_agent.process_message.call_args[0][0]
        assert "Delta" in synthetic
        assert "NYC → LAX" in synthetic

    @pytest.mark.asyncio
    async def test_unknown_action_uses_default_ack(self, mock_agent):
        """Unknown actions get a generic ack."""
        mock_agent.process_message = AsyncMock()

        payload = {
            "action": "mystery_action",
            "cardType": "custom",
            "cardData": {},
        }
        await mock_agent._handle_card_action(payload, "session-1")

        ack_text = mock_agent.gateway.stream_text.call_args[0][0]
        assert "mystery_action" in ack_text

    @pytest.mark.asyncio
    async def test_process_message_error_streams_error(self, mock_agent):
        """If process_message raises, error is streamed to user."""
        mock_agent.process_message = AsyncMock(
            side_effect=RuntimeError("Claude is down"),
        )

        payload = {
            "action": "save",
            "cardType": "flight",
            "cardData": {"title": "Test"},
        }
        await mock_agent._handle_card_action(payload, "session-1")

        # Should have two stream_text calls: ack + error
        assert mock_agent.gateway.stream_text.call_count == 2
        error_text = mock_agent.gateway.stream_text.call_args_list[1][0][0]
        assert "Failed" in error_text
        assert "Claude is down" in error_text

    @pytest.mark.asyncio
    async def test_session_id_passed_through(self, mock_agent):
        """Session ID is passed to both stream_text and process_message."""
        mock_agent.process_message = AsyncMock()

        payload = {
            "action": "book",
            "cardType": "flight",
            "cardData": {},
        }
        await mock_agent._handle_card_action(payload, "my-session-42")

        # stream_text called with session_id
        assert mock_agent.gateway.stream_text.call_args[0][1] == "my-session-42"
        # process_message called with session_id
        assert mock_agent.process_message.call_args[0][1] == "my-session-42"
