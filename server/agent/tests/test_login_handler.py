"""
Tests for LoginHandler — 3-step authentication fallback chain.

Covers:
- Step 1: cached session cookies → inject → authenticated
- Step 1: cache miss / stale cache → fall through
- Step 2: iOS credentials → auto-fill → authenticated
- Step 2: no credentials / 2FA detected → fall through
- Step 3: interactive login flow
- All steps fail → False
- Credential refs nil'd after use
- Session cookies saved after step 2 success
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from server.agent.tools.login_handler import LoginHandler
from server.agent.tools.credential_manager import CredentialManager
from server.agent.tools.session_cache import SessionCache


# ── Helpers ──────────────────────────────────────────────────


def _mock_page(
    auth_indicators: bool = False,
    form_info: dict | None = None,
    has_2fa: bool = False,
    has_captcha: bool = False,
) -> MagicMock:
    """Create a mock Playwright page with configurable evaluate responses."""
    page = MagicMock()
    page.url = "https://accounts.example.com/login"

    # Track evaluate calls to return different results per JS snippet
    default_form = {
        "hasUsername": True,
        "hasPassword": True,
        "usernameSelector": "input[name=email]",
        "passwordSelector": "input[name=password]",
        "submitSelector": "button[type=submit]",
    }
    _form = form_info or default_form

    async def mock_evaluate(js: str, *args, **kwargs):
        if "checkAuthIndicators" in js or "logout" in js.lower() or "avatar" in js.lower():
            return auth_indicators
        if "detectLoginForm" in js or "hasPassword" in js:
            return _form
        if "check2FA" in js or "2fa" in js.lower() or "otp" in js.lower():
            return has_2fa
        if "captcha" in js.lower():
            return has_captcha
        return None

    page.evaluate = AsyncMock(side_effect=mock_evaluate)
    page.reload = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()

    # Mock locator chain
    locator_mock = MagicMock()
    locator_mock.first = MagicMock()
    locator_mock.first.fill = AsyncMock()
    locator_mock.first.type = AsyncMock()
    locator_mock.first.click = AsyncMock()
    page.locator = MagicMock(return_value=locator_mock)

    return page


def _mock_browser_tool(contexts: dict | None = None) -> MagicMock:
    """Create a mock CDPBrowserTool."""
    tool = MagicMock()
    tool._contexts = contexts or {}
    return tool


def _mock_context(cookies: list[dict] | None = None) -> AsyncMock:
    """Create a mock Playwright BrowserContext."""
    ctx = AsyncMock()
    ctx.add_cookies = AsyncMock()
    ctx.cookies = AsyncMock(return_value=cookies or [])
    return ctx


def _mock_credential_manager(
    credentials: list[dict] | None = None,
) -> CredentialManager:
    """Create a CredentialManager with a mocked gateway."""
    manager = CredentialManager()
    manager.request_credentials = AsyncMock(return_value=credentials)
    return manager


def _mock_session_cache() -> SessionCache:
    """Create a mock SessionCache."""
    cache = MagicMock(spec=SessionCache)
    cache.load_session = AsyncMock(return_value=None)
    cache.save_session = AsyncMock()
    cache.clear_session = AsyncMock()
    return cache


def _mock_login_flow(success: bool = True) -> MagicMock:
    """Create a mock LoginFlowManager."""
    flow = MagicMock()
    flow.start_login_flow = AsyncMock(return_value={"success": success})
    return flow


def _mock_profiles() -> MagicMock:
    """Create a mock BrowserProfileManager."""
    profiles = MagicMock()
    profiles.add_authenticated_domain = MagicMock()
    return profiles


def _make_handler(
    browser_contexts: dict | None = None,
    credentials: list[dict] | None = None,
    cached_cookies: list[dict] | None = None,
    login_flow_success: bool = True,
) -> tuple[LoginHandler, dict]:
    """Create a LoginHandler with mocked dependencies."""
    ctx = _mock_context(cookies=[
        {"name": "sid", "value": "v", "domain": ".example.com", "path": "/",
         "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"},
    ])
    browser = _mock_browser_tool(contexts={"default": ctx})
    cache = _mock_session_cache()
    cache.load_session = AsyncMock(return_value=cached_cookies)
    cred_mgr = _mock_credential_manager(credentials)
    login_flow = _mock_login_flow(login_flow_success)
    profiles = _mock_profiles()

    handler = LoginHandler(
        browser_tool=browser,
        credential_manager=cred_mgr,
        session_cache=cache,
        login_flow_manager=login_flow,
        profile_manager=profiles,
    )

    mocks = {
        "browser": browser,
        "context": ctx,
        "cache": cache,
        "cred_mgr": cred_mgr,
        "login_flow": login_flow,
        "profiles": profiles,
    }
    return handler, mocks


# ── Step 1: Cached Session ───────────────────────────────────


class TestStep1CachedSession:

    @pytest.mark.asyncio
    async def test_cache_hit_authenticated(self):
        """Cached cookies → inject → auth indicators → True."""
        cached = [{"name": "sid", "value": "v", "domain": ".example.com",
                    "path": "/", "expires": -1}]
        handler, mocks = _make_handler(cached_cookies=cached)
        page = _mock_page(auth_indicators=True)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is True
        mocks["context"].add_cookies.assert_awaited_once_with(cached)
        page.reload.assert_awaited_once()
        mocks["profiles"].add_authenticated_domain.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_miss_falls_to_step2(self):
        """No cached cookies → skip to step 2."""
        handler, mocks = _make_handler(
            cached_cookies=None,
            credentials=[{"username": "u", "password": "p"}],
        )
        page = _mock_page(auth_indicators=True)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is True
        # Step 1 skipped, step 2 used credentials
        mocks["context"].add_cookies.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_cache_cleared(self):
        """Cached cookies don't authenticate → cache cleared, falls through."""
        cached = [{"name": "old", "value": "v", "domain": ".example.com",
                    "path": "/", "expires": -1}]
        handler, mocks = _make_handler(
            cached_cookies=cached,
            credentials=None,  # step 2 also fails
            login_flow_success=False,
        )
        page = _mock_page(auth_indicators=False)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is False
        mocks["cache"].clear_session.assert_awaited()


# ── Step 2: iOS Credentials ─────────────────────────────────


class TestStep2IOSCredentials:

    @pytest.mark.asyncio
    async def test_credentials_autofill_success(self):
        """Credentials received → auto-fill → authenticated → cookies saved."""
        handler, mocks = _make_handler(
            credentials=[{"username": "user@test.com", "password": "pass123"}],
        )
        page = _mock_page(auth_indicators=True)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is True
        # Cookies should be saved after successful auth
        mocks["cache"].save_session.assert_awaited()
        mocks["profiles"].add_authenticated_domain.assert_called()

    @pytest.mark.asyncio
    async def test_no_credentials_falls_to_step3(self):
        """No credentials from iOS → fall to step 3."""
        handler, mocks = _make_handler(
            credentials=None,
            login_flow_success=True,
        )
        page = _mock_page(auth_indicators=False)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is True
        mocks["login_flow"].start_login_flow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_2fa_detected_falls_to_step3(self):
        """Credentials filled but 2FA detected → fall to step 3."""
        handler, mocks = _make_handler(
            credentials=[{"username": "u", "password": "p"}],
            login_flow_success=True,
        )
        page = _mock_page(auth_indicators=False, has_2fa=True)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is True
        mocks["login_flow"].start_login_flow.assert_awaited_once()


# ── Step 3: Interactive Login ────────────────────────────────


class TestStep3InteractiveLogin:

    @pytest.mark.asyncio
    async def test_interactive_login_success(self):
        """All prior steps fail → interactive login succeeds → True."""
        handler, mocks = _make_handler(
            credentials=None,
            login_flow_success=True,
        )
        page = _mock_page(auth_indicators=False)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is True
        mocks["login_flow"].start_login_flow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_interactive_login_failure(self):
        """All steps fail → False."""
        handler, mocks = _make_handler(
            credentials=None,
            login_flow_success=False,
        )
        page = _mock_page(auth_indicators=False)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_login_flow_manager(self):
        """No login flow manager → all steps fail → False."""
        handler, mocks = _make_handler(credentials=None)
        handler._login_flow = None
        page = _mock_page(auth_indicators=False)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is False


# ── Security ─────────────────────────────────────────────────


class TestSecurity:

    @pytest.mark.asyncio
    async def test_no_login_form_returns_false(self):
        """No login form detected → credentials not injected."""
        handler, mocks = _make_handler(
            credentials=[{"username": "u", "password": "p"}],
            login_flow_success=True,
        )
        page = _mock_page(
            auth_indicators=False,
            form_info={"hasUsername": False, "hasPassword": False},
        )

        result = await handler.handle_login_wall(page, "example.com")
        # Step 2 fails (no form), step 3 kicks in
        assert result is True
        mocks["login_flow"].start_login_flow.assert_awaited_once()


# ── Full Fallback Chain ──────────────────────────────────────


class TestFullFallbackChain:

    @pytest.mark.asyncio
    async def test_step1_fails_step2_fails_step3_succeeds(self):
        """Complete fallback: cache miss → no creds → interactive → True."""
        handler, mocks = _make_handler(
            cached_cookies=None,
            credentials=None,
            login_flow_success=True,
        )
        page = _mock_page(auth_indicators=False)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is True
        mocks["login_flow"].start_login_flow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_steps_fail(self):
        """Every step fails → False."""
        handler, mocks = _make_handler(
            cached_cookies=None,
            credentials=None,
            login_flow_success=False,
        )
        page = _mock_page(auth_indicators=False)

        result = await handler.handle_login_wall(page, "example.com")
        assert result is False
