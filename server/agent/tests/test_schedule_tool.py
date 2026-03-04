"""
Tests for ScheduleTool.

Covers:
- Tool initialization and properties
- create_watch (valid, preset resolution, missing fields)
- list_watches (populated, empty)
- remove_watch, pause_watch, resume_watch
- No gateway configured
- Unknown action
- Gateway error responses
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from server.agent.tools.schedule import INTERVAL_PRESETS, ScheduleTool


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway():
    gw = AsyncMock()
    gw.send_request = AsyncMock(
        return_value={
            "status": "created",
            "jobId": "job-123",
            "nextRun": "2026-03-04T09:00:00Z",
        }
    )
    return gw


@pytest.fixture
def tool(mock_gateway):
    return ScheduleTool(gateway_client=mock_gateway)


# ── Init tests ───────────────────────────────────────────────────────


class TestInit:
    def test_name(self):
        tool = ScheduleTool()
        assert tool.name == "schedule"

    def test_description_mentions_actions(self):
        tool = ScheduleTool()
        desc = tool.description
        assert "create_watch" in desc
        assert "list_watches" in desc
        assert "remove_watch" in desc

    def test_parameters_has_action_enum(self):
        tool = ScheduleTool()
        action_param = tool.parameters["action"]
        assert action_param["required"] is True
        assert "create_watch" in action_param["enum"]
        assert "list_watches" in action_param["enum"]
        assert "remove_watch" in action_param["enum"]
        assert "pause_watch" in action_param["enum"]
        assert "resume_watch" in action_param["enum"]

    def test_set_gateway_client(self):
        tool = ScheduleTool()
        assert tool._gateway is None
        mock = AsyncMock()
        tool.set_gateway_client(mock)
        assert tool._gateway is mock


# ── create_watch tests ───────────────────────────────────────────────


class TestCreateWatch:
    @pytest.mark.asyncio
    async def test_create_watch_sends_request(self, tool, mock_gateway):
        result = await tool.execute(
            action="create_watch",
            description="Monitor GPU prices",
            check_instructions="Check if RTX 5090 drops below $1500",
            interval="daily_morning",
            skill_name="price-monitor",
            payload={"url": "https://example.com/gpu"},
        )

        assert result.success
        assert "job-123" in result.output
        assert "2026-03-04T09:00:00Z" in result.output

        mock_gateway.send_request.assert_called_once_with(
            "schedule.create",
            {
                "cronExpression": "0 9 * * *",
                "skillName": "price-monitor",
                "taskDescription": "Monitor GPU prices",
                "checkInstructions": "Check if RTX 5090 drops below $1500",
                "payload": {"url": "https://example.com/gpu"},
            },
        )

    @pytest.mark.asyncio
    async def test_create_watch_resolves_preset(self, tool, mock_gateway):
        await tool.execute(
            action="create_watch",
            description="Check flights",
            check_instructions="Look for SFO-JFK under $300",
            interval="every_6_hours",
        )

        call_args = mock_gateway.send_request.call_args
        assert call_args[0][1]["cronExpression"] == "0 */6 * * *"

    @pytest.mark.asyncio
    async def test_create_watch_raw_cron_passthrough(self, tool, mock_gateway):
        await tool.execute(
            action="create_watch",
            description="Custom schedule",
            check_instructions="Check something",
            interval="30 2 * * 5",
        )

        call_args = mock_gateway.send_request.call_args
        assert call_args[0][1]["cronExpression"] == "30 2 * * 5"

    @pytest.mark.asyncio
    async def test_create_watch_default_interval(self, tool, mock_gateway):
        await tool.execute(
            action="create_watch",
            description="Default interval watch",
            check_instructions="Check something",
        )

        call_args = mock_gateway.send_request.call_args
        # Default is every_6_hours -> "0 */6 * * *"
        assert call_args[0][1]["cronExpression"] == "0 */6 * * *"

    @pytest.mark.asyncio
    async def test_create_watch_default_skill(self, tool, mock_gateway):
        await tool.execute(
            action="create_watch",
            description="Check prices",
            check_instructions="Check GPU prices",
        )

        call_args = mock_gateway.send_request.call_args
        assert call_args[0][1]["skillName"] == "price-monitor"

    @pytest.mark.asyncio
    async def test_create_watch_missing_description(self, tool):
        result = await tool.execute(
            action="create_watch",
            check_instructions="Check something",
        )

        assert not result.success
        assert "description" in result.output

    @pytest.mark.asyncio
    async def test_create_watch_missing_instructions(self, tool):
        result = await tool.execute(
            action="create_watch",
            description="Watch something",
        )

        assert not result.success
        assert "check_instructions" in result.output

    @pytest.mark.asyncio
    async def test_create_watch_gateway_error_response(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {
            "error": "INVALID_CRON",
            "message": "Invalid cron expression",
        }

        result = await tool.execute(
            action="create_watch",
            description="Bad watch",
            check_instructions="Check something",
            interval="not-a-cron",
        )

        assert not result.success
        assert "Invalid cron expression" in result.output

    @pytest.mark.asyncio
    async def test_create_watch_gateway_exception(self, tool, mock_gateway):
        mock_gateway.send_request.side_effect = ConnectionError("disconnected")

        result = await tool.execute(
            action="create_watch",
            description="Watch something",
            check_instructions="Check it",
        )

        assert not result.success
        assert "disconnected" in result.output


# ── list_watches tests ───────────────────────────────────────────────


class TestListWatches:
    @pytest.mark.asyncio
    async def test_list_watches(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {
            "jobs": [
                {
                    "id": "job-001",
                    "taskDescription": "Monitor GPU prices",
                    "cronExpression": "0 */6 * * *",
                    "active": True,
                    "lastChecked": "2026-03-03T12:00:00Z",
                    "nextRun": "2026-03-03T18:00:00Z",
                },
                {
                    "id": "job-002",
                    "taskDescription": "Flight tracker SFO-JFK",
                    "cronExpression": "0 9 * * *",
                    "active": False,
                    "lastChecked": "2026-03-03T09:00:00Z",
                    "nextRun": "2026-03-04T09:00:00Z",
                },
            ]
        }

        result = await tool.execute(action="list_watches")

        assert result.success
        assert "job-001" in result.output
        assert "job-002" in result.output
        assert "Monitor GPU prices" in result.output
        assert "Flight tracker SFO-JFK" in result.output
        assert "paused" in result.output  # job-002 is inactive

        mock_gateway.send_request.assert_called_once_with("schedule.list", {})

    @pytest.mark.asyncio
    async def test_list_watches_empty(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {"jobs": []}

        result = await tool.execute(action="list_watches")

        assert result.success
        assert "No active watches" in result.output

    @pytest.mark.asyncio
    async def test_list_watches_gateway_error(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {
            "error": "INTERNAL",
            "message": "Database unavailable",
        }

        result = await tool.execute(action="list_watches")

        assert not result.success
        assert "Database unavailable" in result.output


# ── remove_watch tests ───────────────────────────────────────────────


class TestRemoveWatch:
    @pytest.mark.asyncio
    async def test_remove_watch(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {"status": "removed"}

        result = await tool.execute(action="remove_watch", watch_id="job-123")

        assert result.success
        assert "job-123" in result.output
        assert "removed" in result.output

        mock_gateway.send_request.assert_called_once_with(
            "schedule.remove", {"watchId": "job-123"}
        )

    @pytest.mark.asyncio
    async def test_remove_watch_missing_id(self, tool):
        result = await tool.execute(action="remove_watch")

        assert not result.success
        assert "watch_id" in result.output

    @pytest.mark.asyncio
    async def test_remove_watch_gateway_error(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {
            "error": "NOT_FOUND",
            "message": "Watch not found",
        }

        result = await tool.execute(action="remove_watch", watch_id="bad-id")

        assert not result.success
        assert "Watch not found" in result.output


# ── pause_watch tests ────────────────────────────────────────────────


class TestPauseWatch:
    @pytest.mark.asyncio
    async def test_pause_watch(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {"status": "paused"}

        result = await tool.execute(action="pause_watch", watch_id="job-456")

        assert result.success
        assert "job-456" in result.output
        assert "paused" in result.output

        mock_gateway.send_request.assert_called_once_with(
            "schedule.pause", {"watchId": "job-456"}
        )

    @pytest.mark.asyncio
    async def test_pause_watch_missing_id(self, tool):
        result = await tool.execute(action="pause_watch")

        assert not result.success
        assert "watch_id" in result.output

    @pytest.mark.asyncio
    async def test_pause_watch_gateway_error(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {
            "error": "NOT_FOUND",
            "message": "Watch not found",
        }

        result = await tool.execute(action="pause_watch", watch_id="bad-id")

        assert not result.success
        assert "Watch not found" in result.output


# ── resume_watch tests ───────────────────────────────────────────────


class TestResumeWatch:
    @pytest.mark.asyncio
    async def test_resume_watch(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {"status": "resumed"}

        result = await tool.execute(action="resume_watch", watch_id="job-789")

        assert result.success
        assert "job-789" in result.output
        assert "resumed" in result.output

        mock_gateway.send_request.assert_called_once_with(
            "schedule.resume", {"watchId": "job-789"}
        )

    @pytest.mark.asyncio
    async def test_resume_watch_missing_id(self, tool):
        result = await tool.execute(action="resume_watch")

        assert not result.success
        assert "watch_id" in result.output

    @pytest.mark.asyncio
    async def test_resume_watch_gateway_error(self, tool, mock_gateway):
        mock_gateway.send_request.return_value = {
            "error": "NOT_FOUND",
            "message": "Watch not found",
        }

        result = await tool.execute(action="resume_watch", watch_id="bad-id")

        assert not result.success
        assert "Watch not found" in result.output


# ── No gateway / unknown action ──────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_gateway(self):
        tool = ScheduleTool(gateway_client=None)

        result = await tool.execute(action="create_watch")

        assert not result.success
        assert "Gateway client not available" in result.output

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool):
        result = await tool.execute(action="explode")

        assert not result.success
        assert "Unknown action" in result.output
        assert "explode" in result.output


# ── Preset coverage ──────────────────────────────────────────────────


class TestPresets:
    def test_all_presets_are_valid_cron(self):
        """Every preset value should have 5 space-separated fields."""
        for key, cron in INTERVAL_PRESETS.items():
            fields = cron.split()
            assert len(fields) == 5, f"Preset {key!r} has {len(fields)} fields, expected 5"

    def test_preset_keys_match_docs(self):
        expected = {
            "every_5_minutes",
            "every_15_minutes",
            "every_hour",
            "every_6_hours",
            "daily_morning",
            "daily_evening",
            "weekly",
        }
        assert set(INTERVAL_PRESETS.keys()) == expected
