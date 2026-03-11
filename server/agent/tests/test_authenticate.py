"""
Tests for the CDPBrowserTool.authenticate action.

Tests:
- Happy path: auto-fill credentials → submit → authenticated
- Already authenticated: skip login form
- No credentials found: falls back to manual login flow
- 2FA detected after submit: falls back to manual login flow
- CAPTCHA detected: falls back to manual login flow
- No login form on page: falls back to manual
- Multi-step login (username → next → password)
- Auto-fill exception: falls back to manual
- No login flow manager: returns error on fallback
- credential_name param matching
"""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.agent.tools.browser_cdp import (
    CDPBrowserTool,
    JS_CHECK_AUTH_INDICATORS,
    JS_CHECK_2FA,
    JS_CHECK_CAPTCHA,
    JS_DETECT_LOGIN_FORM,
)
from server.agent.tools.tool_registry import ToolResult


# ── Mock Page ─────────────────────────────────────────────────

@dataclass
class MockAuthPage:
    """Mock Playwright page for authenticate tests."""
    url: str = "https://accounts.example.com/login"
    _title: str = "Login"
    _closed: bool = False
    _auth_indicators: bool = False
    _has_2fa: bool = False
    _has_captcha: bool = False
    _form_info: dict = field(default_factory=lambda: {
        "hasPassword": True,
        "hasUsername": True,
        "hasSubmit": True,
        "usernameSelector": "#email",
        "passwordSelector": "#password",
        "submitSelector": "#submit",
    })

    def is_closed(self) -> bool:
        return self._closed

    async def title(self) -> str:
        return self._title

    def __post_init__(self):
        self._locators: dict[str, MagicMock] = {}
        self.keyboard = MagicMock()
        self.keyboard.press = AsyncMock()

    async def evaluate(self, script, *args):
        if script is JS_CHECK_AUTH_INDICATORS or "logout" in str(script):
            return self._auth_indicators
        if script is JS_DETECT_LOGIN_FORM or "hasPassword" in str(script):
            return self._form_info
        if script is JS_CHECK_2FA or "one-time-code" in str(script):
            return self._has_2fa
        if script is JS_CHECK_CAPTCHA or "recaptcha" in str(script):
            return self._has_captcha
        return None

    def locator(self, selector: str):
        if selector not in self._locators:
            loc = MagicMock()
            first = MagicMock()
            first.fill = AsyncMock()
            first.type = AsyncMock()
            first.click = AsyncMock()
            first.scroll_into_view_if_needed = AsyncMock()
            loc.first = first
            self._locators[selector] = loc
        return self._locators[selector]

    async def wait_for_load_state(self, state: str, timeout: int = 5000):
        await asyncio.sleep(0)

    async def screenshot(self, **kwargs) -> bytes:
        return b"fake"


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def mock_page():
    return MockAuthPage()


@pytest.fixture
def mock_credential_lookup():
    """Returns a lookup function that finds creds for example.com."""
    def lookup(url: str):
        if "example.com" in url:
            return {
                "username": "user@example.com",
                "password": "s3cret",
                "name": "example-login",
            }
        return None
    return lookup


@pytest.fixture
def mock_profile_manager():
    pm = MagicMock()
    pm.add_authenticated_domain = MagicMock()
    pm.get_profile = MagicMock(return_value={"name": "default"})
    pm.get_or_create_default = MagicMock()
    return pm


@pytest.fixture
def mock_login_flow_manager():
    lfm = MagicMock()
    lfm.start_login_flow = AsyncMock(return_value={"success": True, "profile": "default", "url": ""})
    return lfm


@pytest.fixture
def browser_tool(mock_credential_lookup, mock_profile_manager, mock_login_flow_manager):
    tool = CDPBrowserTool(
        profile_manager=mock_profile_manager,
        credential_lookup=mock_credential_lookup,
    )
    tool._login_flow_manager = mock_login_flow_manager
    tool._active_profile = "default"
    # Mock _navigate to skip SSRF/DNS checks and page.goto() in tests
    tool._navigate = AsyncMock(return_value={"success": True, "url": ""})
    return tool


# ── Tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authenticate_happy_path(browser_tool, mock_page):
    """Auto-fill creds → submit → page shows auth indicators → success."""
    # After submit, auth indicators appear
    async def evolving_evaluate(script, *args):
        return await mock_page.evaluate(script, *args)

    # Sequence: first check auth=False, detect form, fill, submit, then auth=True
    call_count = {"auth": 0}
    original_evaluate = mock_page.evaluate

    async def patched_evaluate(script, *args):
        if script is JS_CHECK_AUTH_INDICATORS or "logout" in str(script):
            call_count["auth"] += 1
            # First call: not authenticated yet
            if call_count["auth"] <= 1:
                return False
            # After submit: authenticated
            return True
        return await original_evaluate(script, *args)

    mock_page.evaluate = patched_evaluate

    result = await browser_tool._authenticate(mock_page, {
        "url": "https://accounts.example.com/login",
    })

    assert result["success"] is True
    assert result["status"] == "authenticated"
    assert result["domain"] == "accounts.example.com"
    assert result["credential_used"] == "example-login"
    assert result["authenticated"] is True


@pytest.mark.asyncio
async def test_authenticate_already_authenticated(browser_tool, mock_page, mock_profile_manager):
    """If already authenticated, skip login entirely."""
    mock_page._auth_indicators = True

    result = await browser_tool._authenticate(mock_page, {
        "url": "https://accounts.example.com/",
    })

    assert result["success"] is True
    assert result["status"] == "already_authenticated"
    assert result["domain"] == "accounts.example.com"
    mock_profile_manager.add_authenticated_domain.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_no_credentials_fallback(browser_tool, mock_page, mock_login_flow_manager):
    """No stored credentials → falls back to manual login flow."""
    # URL that doesn't match any stored creds
    mock_page.url = "https://unknown-site.com/login"

    result = await browser_tool._authenticate(mock_page, {
        "url": "https://unknown-site.com/login",
    })

    assert result["success"] is True
    assert result["status"] == "manual_login_started"
    assert "No stored credentials" in result["reason"]
    mock_login_flow_manager.start_login_flow.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_2fa_detected(browser_tool, mock_page, mock_login_flow_manager):
    """After filling creds, 2FA is detected → manual handoff."""
    call_count = {"auth": 0}
    original_evaluate = mock_page.evaluate

    async def patched_evaluate(script, *args):
        if script is JS_CHECK_AUTH_INDICATORS or "logout" in str(script):
            return False  # Never authenticated (2FA blocks)
        if script is JS_CHECK_2FA or "one-time-code" in str(script):
            return True  # 2FA detected
        return await original_evaluate(script, *args)

    mock_page.evaluate = patched_evaluate

    result = await browser_tool._authenticate(mock_page, {
        "url": "https://accounts.example.com/login",
    })

    assert result["success"] is True
    assert result["status"] == "2fa_manual_handoff"
    assert "2FA" in result["reason"]
    mock_login_flow_manager.start_login_flow.assert_called_once()


@pytest.mark.asyncio
async def test_authenticate_captcha_detected(browser_tool, mock_page, mock_login_flow_manager):
    """After filling creds, CAPTCHA is detected → manual handoff."""
    original_evaluate = mock_page.evaluate

    async def patched_evaluate(script, *args):
        if script is JS_CHECK_AUTH_INDICATORS or "logout" in str(script):
            return False
        if script is JS_CHECK_CAPTCHA or "recaptcha" in str(script):
            return True  # CAPTCHA detected
        return await original_evaluate(script, *args)

    mock_page.evaluate = patched_evaluate

    result = await browser_tool._authenticate(mock_page, {
        "url": "https://accounts.example.com/login",
    })

    assert result["success"] is True
    assert result["status"] == "2fa_manual_handoff"
    assert "CAPTCHA" in result["reason"]


@pytest.mark.asyncio
async def test_authenticate_no_login_form(browser_tool, mock_page, mock_login_flow_manager):
    """No login form on page → falls back to manual."""
    mock_page._form_info = {
        "hasPassword": False,
        "hasUsername": False,
        "hasSubmit": False,
    }

    result = await browser_tool._authenticate(mock_page, {
        "url": "https://accounts.example.com/",
    })

    assert result["success"] is True
    assert result["status"] == "manual_login_started"
    assert "No login form" in result["reason"]


@pytest.mark.asyncio
async def test_authenticate_missing_url():
    """Missing URL parameter → error."""
    tool = CDPBrowserTool()
    page = MockAuthPage()

    result = await tool._authenticate(page, {})

    assert result["success"] is False
    assert "url" in result["error"].lower()


@pytest.mark.asyncio
async def test_authenticate_no_login_flow_manager_on_fallback(mock_page, mock_credential_lookup, mock_profile_manager):
    """No login flow manager when fallback needed → error."""
    tool = CDPBrowserTool(
        profile_manager=mock_profile_manager,
        credential_lookup=mock_credential_lookup,
    )
    tool._active_profile = "default"
    tool._navigate = AsyncMock(return_value={"success": True, "url": ""})
    # Do NOT set _login_flow_manager

    # URL that won't match credentials
    mock_page.url = "https://unknown.com/login"

    result = await tool._authenticate(mock_page, {
        "url": "https://unknown.com/login",
    })

    assert result["success"] is False
    assert "not available" in result["error"].lower()


@pytest.mark.asyncio
async def test_authenticate_multi_step_login(browser_tool, mock_page, mock_login_flow_manager):
    """Multi-step login: username page → click next → password page → submit."""
    step = {"count": 0}
    original_evaluate = mock_page.evaluate

    async def patched_evaluate(script, *args):
        if script is JS_CHECK_AUTH_INDICATORS or "logout" in str(script):
            # After step 2 (password submitted), authenticated
            return step["count"] >= 2
        if script is JS_DETECT_LOGIN_FORM or "hasPassword" in str(script):
            step["count"] += 1
            if step["count"] == 1:
                # First page: username only, no password
                return {
                    "hasPassword": False,
                    "hasUsername": True,
                    "hasSubmit": True,
                    "usernameSelector": "#email",
                    "passwordSelector": None,
                    "submitSelector": "#next",
                }
            else:
                # Second page: password field appears
                return {
                    "hasPassword": True,
                    "hasUsername": False,
                    "hasSubmit": True,
                    "usernameSelector": None,
                    "passwordSelector": "#password",
                    "submitSelector": "#submit",
                }
        return await original_evaluate(script, *args)

    mock_page.evaluate = patched_evaluate

    result = await browser_tool._authenticate(mock_page, {
        "url": "https://accounts.example.com/login",
    })

    assert result["success"] is True
    assert result["authenticated"] is True


@pytest.mark.asyncio
async def test_authenticate_autofill_exception(browser_tool, mock_page, mock_login_flow_manager):
    """If auto-fill throws, fall back to manual."""
    original_evaluate = mock_page.evaluate

    async def patched_evaluate(script, *args):
        if script is JS_CHECK_AUTH_INDICATORS or "logout" in str(script):
            return False
        if script is JS_DETECT_LOGIN_FORM or "hasPassword" in str(script):
            return {
                "hasPassword": True,
                "hasUsername": True,
                "hasSubmit": True,
                "usernameSelector": "#email",
                "passwordSelector": "#password",
                "submitSelector": "#submit",
            }
        return await original_evaluate(script, *args)

    mock_page.evaluate = patched_evaluate
    # Make locator.fill() throw
    mock_page._locators = {}
    loc = MagicMock()
    first = MagicMock()
    first.fill = AsyncMock(side_effect=Exception("Playwright error"))
    first.type = AsyncMock()
    loc.first = first
    mock_page._locators["#email"] = loc

    result = await browser_tool._authenticate(mock_page, {
        "url": "https://accounts.example.com/login",
    })

    assert result["success"] is True
    assert result["status"] == "manual_login_started"
    assert "Auto-fill failed" in result["reason"]


# ── CredentialStore.get_site_login tests ──────────────────────

class TestGetSiteLogin:
    """Tests for the site_login credential type and URL matching."""

    def test_site_login_exact_match(self, tmp_path):
        from server.agent.credential_store import CredentialStore
        store = CredentialStore(str(tmp_path / "creds"))
        store.set("gmail", "site_login", {
            "url_pattern": "accounts.google.com",
            "username": "user@gmail.com",
            "password": "pass123",
        })

        result = store.get_site_login("https://accounts.google.com/signin")
        assert result is not None
        assert result["username"] == "user@gmail.com"
        assert result["password"] == "pass123"
        assert result["name"] == "gmail"

    def test_site_login_subdomain_match(self, tmp_path):
        from server.agent.credential_store import CredentialStore
        store = CredentialStore(str(tmp_path / "creds"))
        store.set("google", "site_login", {
            "url_pattern": "google.com",
            "username": "user@gmail.com",
            "password": "pass",
        })

        # accounts.google.com ends with .google.com
        result = store.get_site_login("https://accounts.google.com/login")
        assert result is not None
        assert result["name"] == "google"

    def test_site_login_no_match(self, tmp_path):
        from server.agent.credential_store import CredentialStore
        store = CredentialStore(str(tmp_path / "creds"))
        store.set("gmail", "site_login", {
            "url_pattern": "google.com",
            "username": "user@gmail.com",
            "password": "pass",
        })

        result = store.get_site_login("https://facebook.com/login")
        assert result is None

    def test_site_login_empty_url(self, tmp_path):
        from server.agent.credential_store import CredentialStore
        store = CredentialStore(str(tmp_path / "creds"))

        result = store.get_site_login("")
        assert result is None

    def test_site_login_validation(self, tmp_path):
        from server.agent.credential_store import CredentialStore
        store = CredentialStore(str(tmp_path / "creds"))

        # site_login requires url_pattern, username, password
        with pytest.raises(ValueError, match="url_pattern"):
            store.set("bad", "site_login", {"username": "a", "password": "b"})

    def test_site_login_skips_non_site_login_types(self, tmp_path):
        from server.agent.credential_store import CredentialStore
        store = CredentialStore(str(tmp_path / "creds"))
        # Add an api_key credential — should be skipped
        store.set("google-api", "api_key", {"key": "xxx"})

        result = store.get_site_login("https://google.com")
        assert result is None
