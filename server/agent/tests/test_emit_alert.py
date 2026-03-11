"""
Tests for EmitAlertTool.

Covers:
- Tool initialization and properties
- Successful alert emission with gateway mock
- Missing required fields
- Optional field defaults
- No gateway configured
- Gateway exception handling
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from server.agent.tools.emit_alert import EmitAlertTool


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_gateway():
    gw = AsyncMock()
    gw.emit_watchlist_alert = AsyncMock()
    return gw


@pytest.fixture
def tool(mock_gateway):
    return EmitAlertTool(gateway_client=mock_gateway)


VALID_KWARGS = {
    "watch_id": "job-001",
    "alert_type": "price_drop",
    "title": "RTX 5090 Price Drop",
    "message": "Dropped from $1,799 to $1,549 on StockX",
    "item": "RTX 5090",
    "source": "StockX",
    "previous_value": "1799",
    "current_value": "1549",
}


# ── Init tests ───────────────────────────────────────────────────────


class TestInit:
    def test_name(self):
        tool = EmitAlertTool()
        assert tool.name == "emit_alert"

    def test_description_mentions_alert(self):
        tool = EmitAlertTool()
        desc = tool.description
        assert "alert" in desc.lower()
        assert "watchlist" in desc.lower()

    def test_parameters_has_required_fields(self):
        tool = EmitAlertTool()
        params = tool.parameters
        required = [
            "watch_id", "alert_type", "title", "message",
            "item", "source", "previous_value", "current_value",
        ]
        for field in required:
            assert field in params, f"Missing parameter: {field}"
            assert params[field]["required"] is True, f"{field} should be required"

    def test_parameters_has_optional_fields(self):
        tool = EmitAlertTool()
        params = tool.parameters
        for field in ("threshold", "url"):
            assert field in params, f"Missing parameter: {field}"
            assert params[field]["required"] is False, f"{field} should be optional"

    def test_set_gateway_client(self):
        tool = EmitAlertTool()
        assert tool._gateway is None
        mock = AsyncMock()
        tool.set_gateway_client(mock)
        assert tool._gateway is mock


# ── Successful alert tests ──────────────────────────────────────────


class TestSuccessfulAlert:
    @pytest.mark.asyncio
    async def test_successful_alert_calls_gateway(self, tool, mock_gateway):
        result = await tool.execute(**VALID_KWARGS)

        assert result.success
        assert result.output["status"] == "alert_sent"
        assert result.output["watch_id"] == "job-001"
        assert result.output["alert_type"] == "price_drop"

        mock_gateway.emit_watchlist_alert.assert_called_once_with(
            watch_id="job-001",
            alert_type="price_drop",
            title="RTX 5090 Price Drop",
            message="Dropped from $1,799 to $1,549 on StockX",
            item="RTX 5090",
            source="StockX",
            previous_value="1799",
            current_value="1549",
            threshold="",
            url="",
        )

    @pytest.mark.asyncio
    async def test_optional_fields_passed_through(self, tool, mock_gateway):
        kwargs = {
            **VALID_KWARGS,
            "threshold": "1600",
            "url": "https://stockx.com/rtx-5090",
        }
        result = await tool.execute(**kwargs)

        assert result.success

        call_kwargs = mock_gateway.emit_watchlist_alert.call_args
        assert call_kwargs.kwargs["threshold"] == "1600"
        assert call_kwargs.kwargs["url"] == "https://stockx.com/rtx-5090"

    @pytest.mark.asyncio
    async def test_optional_fields_default(self, tool, mock_gateway):
        result = await tool.execute(**VALID_KWARGS)

        assert result.success

        call_kwargs = mock_gateway.emit_watchlist_alert.call_args
        assert call_kwargs.kwargs["threshold"] == ""
        assert call_kwargs.kwargs["url"] == ""

    @pytest.mark.asyncio
    async def test_values_coerced_to_string(self, tool, mock_gateway):
        kwargs = {**VALID_KWARGS, "previous_value": 1799, "current_value": 1549}
        result = await tool.execute(**kwargs)

        assert result.success

        call_kwargs = mock_gateway.emit_watchlist_alert.call_args
        assert call_kwargs.kwargs["previous_value"] == "1799"
        assert call_kwargs.kwargs["current_value"] == "1549"


# ── Missing field tests ─────────────────────────────────────────────


class TestMissingFields:
    @pytest.mark.asyncio
    async def test_missing_watch_id_fails(self, tool):
        kwargs = {**VALID_KWARGS}
        del kwargs["watch_id"]
        result = await tool.execute(**kwargs)

        assert not result.success
        assert "watch_id" in result.output

    @pytest.mark.asyncio
    async def test_missing_alert_type_fails(self, tool):
        kwargs = {**VALID_KWARGS}
        del kwargs["alert_type"]
        result = await tool.execute(**kwargs)

        assert not result.success
        assert "alert_type" in result.output

    @pytest.mark.asyncio
    async def test_missing_title_fails(self, tool):
        kwargs = {**VALID_KWARGS}
        del kwargs["title"]
        result = await tool.execute(**kwargs)

        assert not result.success
        assert "title" in result.output

    @pytest.mark.asyncio
    async def test_missing_message_fails(self, tool):
        kwargs = {**VALID_KWARGS}
        del kwargs["message"]
        result = await tool.execute(**kwargs)

        assert not result.success
        assert "message" in result.output

    @pytest.mark.asyncio
    async def test_missing_item_fails(self, tool):
        kwargs = {**VALID_KWARGS}
        del kwargs["item"]
        result = await tool.execute(**kwargs)

        assert not result.success
        assert "item" in result.output

    @pytest.mark.asyncio
    async def test_missing_source_fails(self, tool):
        kwargs = {**VALID_KWARGS}
        del kwargs["source"]
        result = await tool.execute(**kwargs)

        assert not result.success
        assert "source" in result.output

    @pytest.mark.asyncio
    async def test_missing_previous_value_fails(self, tool):
        kwargs = {**VALID_KWARGS}
        del kwargs["previous_value"]
        result = await tool.execute(**kwargs)

        assert not result.success
        assert "previous_value" in result.output

    @pytest.mark.asyncio
    async def test_missing_current_value_fails(self, tool):
        kwargs = {**VALID_KWARGS}
        del kwargs["current_value"]
        result = await tool.execute(**kwargs)

        assert not result.success
        assert "current_value" in result.output


# ── Edge cases ───────────────────────────────────────────────────────


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_gateway_fails(self):
        tool = EmitAlertTool(gateway_client=None)

        result = await tool.execute(**VALID_KWARGS)

        assert not result.success
        assert "Gateway client not available" in result.output

    @pytest.mark.asyncio
    async def test_gateway_exception(self, tool, mock_gateway):
        mock_gateway.emit_watchlist_alert.side_effect = ConnectionError("disconnected")

        result = await tool.execute(**VALID_KWARGS)

        assert not result.success
        assert "disconnected" in result.output
