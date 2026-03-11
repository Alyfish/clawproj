"""
Tests for SessionContext — Read-Before-Act verification.

Covers: empty state, tool recording, domain detection, file writes,
card data checks, and payment readiness checks.
"""
from __future__ import annotations

import pytest

from server.agent.session_context import SessionContext


# ── Basic state ──────────────────────────────────────────────

def test_empty_session():
    """New SessionContext has no data."""
    ctx = SessionContext()
    assert not ctx.has_any_tool_calls()
    assert not ctx.has_searched()
    assert not ctx.has_real_data("flights")
    assert ctx.tool_calls == []
    assert ctx.files_written == set()
    assert ctx.verified_domains == set()


def test_has_any_tool_calls():
    """Empty → False, after record → True."""
    ctx = SessionContext()
    assert not ctx.has_any_tool_calls()
    ctx.record_tool_call("load_skill")
    assert ctx.has_any_tool_calls()


# ── Search detection ─────────────────────────────────────────

def test_record_bash_search():
    """bash with 'curl searxng' → has_searched()."""
    ctx = SessionContext()
    ctx.record_tool_call("bash_execute", "curl searxng.local/search?q=test")
    assert ctx.has_searched()


def test_record_browser():
    """browser call → has_real_data('browser')."""
    ctx = SessionContext()
    ctx.record_tool_call("browser", "navigate https://example.com")
    assert ctx.has_real_data("browser")
    assert ctx.has_searched()


# ── Domain detection ─────────────────────────────────────────

def test_record_bash_prices():
    """bash with 'jordan price' → has_real_data('prices')."""
    ctx = SessionContext()
    ctx.record_tool_call("bash_execute", "curl 'stockx.com/jordan-1?price=200'")
    assert ctx.has_real_data("prices")


def test_domain_detection_flights():
    """bash with 'kayak flights' → has_real_data('flights')."""
    ctx = SessionContext()
    ctx.record_tool_call("bash_execute", "curl 'kayak.com/flights?from=JFK'")
    assert ctx.has_real_data("flights")


def test_domain_detection_apartments():
    """bash with 'zillow rent' → has_real_data('apartments')."""
    ctx = SessionContext()
    ctx.record_tool_call("bash_execute", "curl 'zillow.com/rent/nyc'")
    assert ctx.has_real_data("apartments")


# ── File write tracking ──────────────────────────────────────

def test_file_write_tracking():
    """record_file_write → in files_written."""
    ctx = SessionContext()
    ctx.record_file_write("/workspace/data/flights.json")
    assert "/workspace/data/flights.json" in ctx.files_written


# ── Card data checks ────────────────────────────────────────

def test_card_without_search_injects_warning():
    """check_card_data('flight', {}) with empty session → warning string."""
    ctx = SessionContext()
    warning = ctx.check_card_data("flight", {})
    assert warning is not None
    assert "VERIFICATION REQUIRED" in warning
    assert "flights" in warning


def test_card_after_search_no_warning():
    """search then check_card_data → None."""
    ctx = SessionContext()
    ctx.record_tool_call("bash_execute", "curl 'kayak.com/flights?from=LAX'")
    warning = ctx.check_card_data("flight", {})
    assert warning is None


# ── Payment readiness ───────────────────────────────────────

def test_payment_blocked_without_data():
    """check_payment_readiness() with empty session → rejection string."""
    ctx = SessionContext()
    rejection = ctx.check_payment_readiness()
    assert rejection is not None
    assert "PAYMENT BLOCKED" in rejection


def test_payment_allowed_after_search():
    """search then check_payment_readiness() → None."""
    ctx = SessionContext()
    ctx.record_tool_call("web_search", "cheapest flight JFK to LAX")
    rejection = ctx.check_payment_readiness()
    assert rejection is None
