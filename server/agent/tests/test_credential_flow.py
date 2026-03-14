"""
Integration tests for the full credential flow.

Tests wire real components together (not mocks-of-mocks) to verify:
- Session cache hit skips credential request
- Credential request → auto-fill → authenticated
- Credential fallback chain → interactive login
- Timeout handling
- Credential rules reach LLM context (SOUL.md)
- Credentials never appear in log output
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.agent.tools.session_cache import SessionCache
from server.agent.tools.credential_manager import CredentialManager
from server.agent.tools.login_handler import LoginHandler
from server.agent.context_builder import ContextBuilder


# ── Helpers ──────────────────────────────────────────────────


def _mock_page(
    auth_indicators: bool = False,
    form_info: dict | None = None,
    has_2fa: bool = False,
) -> MagicMock:
    """Create a mock Playwright page with configurable evaluate responses."""
    page = MagicMock()
    page.url = "https://accounts.example.com/login"

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
            return False
        return None

    page.evaluate = AsyncMock(side_effect=mock_evaluate)
    page.reload = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.keyboard = MagicMock()
    page.keyboard.press = AsyncMock()

    locator_mock = MagicMock()
    locator_mock.first = MagicMock()
    locator_mock.first.fill = AsyncMock()
    locator_mock.first.type = AsyncMock()
    locator_mock.first.click = AsyncMock()
    page.locator = MagicMock(return_value=locator_mock)

    return page


def _mock_context(cookies: list[dict] | None = None) -> AsyncMock:
    """Create a mock Playwright BrowserContext."""
    ctx = AsyncMock()
    ctx.add_cookies = AsyncMock()
    ctx.cookies = AsyncMock(return_value=cookies or [])
    return ctx


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


def _make_cookie(
    name: str = "sid",
    value: str = "abc123",
    domain: str = ".example.com",
) -> dict:
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        "expires": -1,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }


# ── Integration Tests ───────────────────────────────────────


class TestCredentialFlowIntegration:
    """Tests that wire real components together."""

    @pytest.mark.asyncio
    async def test_session_cache_hit(self, tmp_path: Path):
        """Real SessionCache with cookies → step 1 succeeds, no credential request."""
        # Wire real SessionCache
        cache = SessionCache(base_dir=str(tmp_path / "sessions"))
        await cache.save_session("example.com", [_make_cookie()])

        # Mock credential manager — should NOT be called
        cred_mgr = CredentialManager(gateway_client=None)
        cred_mgr.request_credentials = AsyncMock(return_value=None)

        # Mock login flow — should NOT be called
        login_flow = _mock_login_flow()

        # Browser context for cookie injection
        ctx = _mock_context(cookies=[_make_cookie()])
        browser = MagicMock()
        browser._contexts = {"default": ctx}

        handler = LoginHandler(
            browser_tool=browser,
            credential_manager=cred_mgr,
            session_cache=cache,
            login_flow_manager=login_flow,
            profile_manager=_mock_profiles(),
        )

        page = _mock_page(auth_indicators=True)
        result = await handler.handle_login_wall(page, "example.com")

        assert result is True
        # Step 1 succeeded — step 2 and 3 never called
        cred_mgr.request_credentials.assert_not_awaited()
        login_flow.start_login_flow.assert_not_awaited()
        # Cookies were injected
        ctx.add_cookies.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_credential_request_and_inject(self, tmp_path: Path):
        """Real CredentialManager with mock gateway → step 2 auto-fills → authenticated."""
        # Real SessionCache (empty — step 1 will miss)
        cache = SessionCache(base_dir=str(tmp_path / "sessions"))

        # Mock gateway that returns credentials
        gateway = AsyncMock()
        gateway.request_credentials = AsyncMock(return_value={
            "requestId": "test-req-id",
            "domain": "example.com",
            "credentials": [
                {"username": "user@test.com", "password": "s3cret_test_pwd"},
            ],
        })

        # Real CredentialManager wired to mock gateway
        cred_mgr = CredentialManager(gateway_client=gateway)

        login_flow = _mock_login_flow()
        ctx = _mock_context(cookies=[_make_cookie()])
        browser = MagicMock()
        browser._contexts = {"default": ctx}

        handler = LoginHandler(
            browser_tool=browser,
            credential_manager=cred_mgr,
            session_cache=cache,
            login_flow_manager=login_flow,
            profile_manager=_mock_profiles(),
        )

        page = _mock_page(auth_indicators=True)
        result = await handler.handle_login_wall(page, "example.com")

        assert result is True
        # Gateway was called for credentials
        gateway.request_credentials.assert_awaited_once()
        # Login flow NOT called (step 2 succeeded)
        login_flow.start_login_flow.assert_not_awaited()
        # Session cookies saved after successful auth
        assert (tmp_path / "sessions" / "example.com.json").exists()

    @pytest.mark.asyncio
    async def test_credential_fallback_to_logincard(self, tmp_path: Path):
        """No credentials → falls through to interactive login (step 3)."""
        cache = SessionCache(base_dir=str(tmp_path / "sessions"))

        # Gateway returns None (no credentials)
        gateway = AsyncMock()
        gateway.request_credentials = AsyncMock(return_value=None)
        cred_mgr = CredentialManager(gateway_client=gateway)

        login_flow = _mock_login_flow(success=True)
        ctx = _mock_context()
        browser = MagicMock()
        browser._contexts = {"default": ctx}

        handler = LoginHandler(
            browser_tool=browser,
            credential_manager=cred_mgr,
            session_cache=cache,
            login_flow_manager=login_flow,
            profile_manager=_mock_profiles(),
        )

        page = _mock_page(auth_indicators=False)
        result = await handler.handle_login_wall(page, "example.com")

        assert result is True
        # Step 3 was reached
        login_flow.start_login_flow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_credential_timeout(self, tmp_path: Path):
        """Gateway timeout → CredentialManager returns None → falls to step 3."""
        cache = SessionCache(base_dir=str(tmp_path / "sessions"))

        # Gateway raises TimeoutError
        gateway = AsyncMock()
        gateway.request_credentials = AsyncMock(
            side_effect=asyncio.TimeoutError("30s timeout"),
        )
        cred_mgr = CredentialManager(gateway_client=gateway)

        login_flow = _mock_login_flow(success=True)
        ctx = _mock_context()
        browser = MagicMock()
        browser._contexts = {"default": ctx}

        handler = LoginHandler(
            browser_tool=browser,
            credential_manager=cred_mgr,
            session_cache=cache,
            login_flow_manager=login_flow,
            profile_manager=_mock_profiles(),
        )

        page = _mock_page(auth_indicators=False)
        result = await handler.handle_login_wall(page, "example.com")

        assert result is True
        login_flow.start_login_flow.assert_awaited_once()


class TestCredentialSecurity:
    """Security-focused tests for credential handling."""

    def test_credentials_not_in_context(self):
        """SOUL.md credential rules are included in the system prompt."""
        soul_path = Path(__file__).parent.parent.parent.parent / "SOUL.md"
        if not soul_path.exists():
            pytest.skip("SOUL.md not found at project root")

        cb = ContextBuilder(soul_path=str(soul_path))
        prompt = cb.build_system_prompt()

        assert "Never expose credentials in chat" in prompt
        assert "Never write credentials to files" in prompt
        assert "Only use credentials for browser injection" in prompt
        assert "Clear credentials immediately after use" in prompt
        assert "TOTP codes are ephemeral" in prompt
        assert "LoginCard is the fallback" in prompt
        assert "Decline credential storage requests" in prompt
        assert "Session cookies are OK to cache" in prompt

    @pytest.mark.asyncio
    async def test_credentials_not_logged(self, tmp_path: Path):
        """Credentials never appear in log output during the flow."""
        test_password = "s3cret_test_pwd_XYZ789"
        test_username = "secret_user_ABC123@test.com"

        # Capture all log output
        captured_records: list[logging.LogRecord] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured_records.append(record)

        # Install handler on root logger to catch everything
        handler = CapturingHandler()
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)

        try:
            cache = SessionCache(base_dir=str(tmp_path / "sessions"))

            gateway = AsyncMock()
            gateway.request_credentials = AsyncMock(return_value={
                "requestId": "test-id",
                "domain": "example.com",
                "credentials": [
                    {"username": test_username, "password": test_password},
                ],
            })
            cred_mgr = CredentialManager(gateway_client=gateway)

            login_flow = _mock_login_flow()
            ctx = _mock_context(cookies=[_make_cookie()])
            browser = MagicMock()
            browser._contexts = {"default": ctx}

            login_handler = LoginHandler(
                browser_tool=browser,
                credential_manager=cred_mgr,
                session_cache=cache,
                login_flow_manager=login_flow,
                profile_manager=_mock_profiles(),
            )

            page = _mock_page(auth_indicators=True)
            await login_handler.handle_login_wall(page, "example.com")

            # Check every log record — password and username must not appear
            for record in captured_records:
                msg = record.getMessage()
                assert test_password not in msg, (
                    f"Password leaked in log: {msg}"
                )
                assert test_username not in msg, (
                    f"Username leaked in log: {msg}"
                )
        finally:
            root_logger.removeHandler(handler)
