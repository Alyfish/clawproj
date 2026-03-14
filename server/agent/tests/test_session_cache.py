"""
Tests for SessionCache — browser cookie persistence.

Covers:
- Save + load round-trip
- Expired cookie filtering
- Session cookie preservation (expires=-1/0)
- Domain sanitization / path traversal rejection
- Cache expiry checks
- Clear session
- Corrupted file handling
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from server.agent.tools.session_cache import SessionCache, _sanitize_domain


# ── Helpers ──────────────────────────────────────────────────


@pytest.fixture
def tmp_cache(tmp_path: Path) -> SessionCache:
    """Create a SessionCache using a temporary directory."""
    return SessionCache(base_dir=str(tmp_path / "sessions"))


def _make_cookie(
    name: str = "session",
    value: str = "abc123",
    domain: str = ".example.com",
    path: str = "/",
    expires: float = -1,
    httpOnly: bool = True,
    secure: bool = True,
    sameSite: str = "Lax",
) -> dict:
    """Create a Playwright-style cookie dict."""
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path,
        "expires": expires,
        "httpOnly": httpOnly,
        "secure": secure,
        "sameSite": sameSite,
    }


# ── Domain Sanitization ─────────────────────────────────────


class TestDomainSanitization:

    def test_valid_domain(self):
        assert _sanitize_domain("example.com") == "example.com"

    def test_uppercase_normalized(self):
        assert _sanitize_domain("Example.COM") == "example.com"

    def test_strips_whitespace(self):
        assert _sanitize_domain("  example.com  ") == "example.com"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            _sanitize_domain("")

    def test_rejects_path_traversal_dots(self):
        with pytest.raises(ValueError, match="path traversal"):
            _sanitize_domain("../etc/passwd")

    def test_rejects_path_traversal_slash(self):
        with pytest.raises(ValueError, match="path traversal"):
            _sanitize_domain("example.com/../../etc")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError, match="path traversal"):
            _sanitize_domain("example.com\\..\\etc")

    def test_rejects_invalid_chars(self):
        with pytest.raises(ValueError, match="Invalid domain"):
            _sanitize_domain("example .com")


# ── Save + Load ──────────────────────────────────────────────


class TestSaveAndLoad:

    @pytest.mark.asyncio
    async def test_save_and_load_round_trip(self, tmp_cache: SessionCache):
        cookies = [
            _make_cookie("sid", "val1"),
            _make_cookie("token", "val2"),
        ]
        await tmp_cache.save_session("example.com", cookies)
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0]["name"] == "sid"
        assert loaded[1]["name"] == "token"

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_cache: SessionCache):
        result = await tmp_cache.load_session("nonexistent.example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_empty_cookies_is_noop(self, tmp_cache: SessionCache):
        await tmp_cache.save_session("example.com", [])
        result = await tmp_cache.load_session("example.com")
        assert result is None


# ── Expiry Filtering ─────────────────────────────────────────


class TestExpiryFiltering:

    @pytest.mark.asyncio
    async def test_expired_cookies_filtered_out(self, tmp_cache: SessionCache):
        past = time.time() - 3600  # 1 hour ago
        cookies = [
            _make_cookie("expired", "val", expires=past),
            _make_cookie("valid", "val", expires=-1),
        ]
        await tmp_cache.save_session("example.com", cookies)
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["name"] == "valid"

    @pytest.mark.asyncio
    async def test_all_expired_returns_none_and_cleans_file(self, tmp_cache: SessionCache):
        past = time.time() - 3600
        cookies = [_make_cookie("expired", "val", expires=past)]
        await tmp_cache.save_session("example.com", cookies)
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is None
        # File should be cleaned up
        path = tmp_cache._domain_to_path("example.com")
        assert not path.exists()

    @pytest.mark.asyncio
    async def test_session_cookies_preserved(self, tmp_cache: SessionCache):
        """Cookies with expires=-1 or expires=0 are session cookies and kept."""
        cookies = [
            _make_cookie("sess1", "val", expires=-1),
            _make_cookie("sess2", "val", expires=0),
        ]
        await tmp_cache.save_session("example.com", cookies)
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is not None
        assert len(loaded) == 2

    @pytest.mark.asyncio
    async def test_future_expiry_preserved(self, tmp_cache: SessionCache):
        future = time.time() + 86400  # 24 hours from now
        cookies = [_make_cookie("valid", "val", expires=future)]
        await tmp_cache.save_session("example.com", cookies)
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is not None
        assert len(loaded) == 1


# ── Check Expiry ─────────────────────────────────────────────


class TestCheckExpiry:

    @pytest.mark.asyncio
    async def test_check_expiry_valid_session(self, tmp_cache: SessionCache):
        cookies = [_make_cookie("sid", "val")]
        await tmp_cache.save_session("example.com", cookies)
        assert await tmp_cache.check_expiry("example.com") is True

    @pytest.mark.asyncio
    async def test_check_expiry_no_session(self, tmp_cache: SessionCache):
        assert await tmp_cache.check_expiry("nonexistent.com") is False

    @pytest.mark.asyncio
    async def test_check_expiry_all_expired(self, tmp_cache: SessionCache):
        past = time.time() - 3600
        cookies = [_make_cookie("expired", "val", expires=past)]
        await tmp_cache.save_session("example.com", cookies)
        assert await tmp_cache.check_expiry("example.com") is False


# ── Clear Session ────────────────────────────────────────────


class TestClearSession:

    @pytest.mark.asyncio
    async def test_clear_session(self, tmp_cache: SessionCache):
        cookies = [_make_cookie()]
        await tmp_cache.save_session("example.com", cookies)
        await tmp_cache.clear_session("example.com")
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_clear_nonexistent_no_error(self, tmp_cache: SessionCache):
        # Should not raise
        await tmp_cache.clear_session("nonexistent.example.com")


# ── Error Handling ───────────────────────────────────────────


class TestErrorHandling:

    @pytest.mark.asyncio
    async def test_corrupted_json_returns_none(self, tmp_cache: SessionCache):
        path = tmp_cache._domain_to_path("example.com")
        path.write_text("NOT VALID JSON", encoding="utf-8")
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_invalid_data_shape_returns_none(self, tmp_cache: SessionCache):
        path = tmp_cache._domain_to_path("example.com")
        path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_missing_cookies_key_returns_none(self, tmp_cache: SessionCache):
        path = tmp_cache._domain_to_path("example.com")
        path.write_text(json.dumps({"domain": "example.com"}), encoding="utf-8")
        loaded = await tmp_cache.load_session("example.com")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_invalid_domain_returns_none(self, tmp_cache: SessionCache):
        loaded = await tmp_cache.load_session("../etc/passwd")
        assert loaded is None
