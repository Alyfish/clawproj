"""
ClawBot CDP Browser Tool

Remote browser automation via Chrome DevTools Protocol.
Connects to a browserless/chromium Docker container using
Playwright's connect_over_cdp() — no local browser binary needed.

Replaces the Node.js sidecar approach (browser_bridge.py) with a
direct CDP connection to a persistent, remote Chrome instance.

Key advantages:
  - Browser survives agent restarts (login sessions persist)
  - No subprocess management (Docker handles the browser lifecycle)
  - Same Playwright API surface (page.evaluate, page.click, etc.)

Design references:
  - server/agent/tools/browser_bridge.py (interface contract, checkpoint pattern)
  - server/agent/tools/browser/src/checkpoint.ts (checkpoint detection logic)
  - server/agent/tools/tool_registry.py (BaseTool ABC, ToolResult)
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from server.agent.tools.browser_js import DOM_WALKER_JS, JS_LOOKUP_REF, JS_CHECK_AUTH_INDICATORS

from server.agent.tools.browser_security import BrowserSecurityPolicy
from server.agent.tools.tool_registry import BaseTool, ToolResult, truncate

logger = logging.getLogger(__name__)

# Lazy imports for playwright — only needed at runtime, not at import time.
# This avoids import errors when playwright isn't installed (e.g., in test environments
# that mock the connection).
_playwright_imported = False
_async_playwright = None
_PWBrowser = None
_PWBrowserContext = None
_PWPage = None
_PWPlaywright = None
_PWError = None


def _import_playwright() -> None:
    """Lazy-import playwright types. Called once on first use."""
    global _playwright_imported, _async_playwright
    global _PWBrowser, _PWBrowserContext, _PWPage, _PWPlaywright, _PWError
    if _playwright_imported:
        return
    from playwright.async_api import (
        async_playwright,
        Browser,
        BrowserContext,
        Page,
        Playwright,
        Error as PlaywrightError,
    )
    _async_playwright = async_playwright
    _PWBrowser = Browser
    _PWBrowserContext = BrowserContext
    _PWPage = Page
    _PWPlaywright = Playwright
    _PWError = PlaywrightError
    _playwright_imported = True


# ── Constants ────────────────────────────────────────────────────────

PAYMENT_URL_PATTERNS = [
    r"/checkout/",
    r"/payment/",
    r"/billing/",
    r"/purchase/",
    r"/order/confirm",
]

SUBMIT_TEXT_PATTERN = re.compile(
    r"submit|confirm|send|place.?order|complete|pay|purchase|book.?now|checkout|sign.?up|register|apply",
    re.IGNORECASE,
)

# JavaScript snippets executed inside the browser via page.evaluate().
# These are ported directly from checkpoint.ts.

JS_CHECK_CARD_FIELDS = """() => {
    try {
        return !!document.querySelector([
            'input[autocomplete*="cc-"]',
            'input[name*="card"]',
            'input[name*="credit"]',
            'input[data-stripe]',
            '[class*="CardField"]',
            '[class*="card-number"]'
        ].join(', '));
    } catch { return false; }
}"""

JS_CHECK_FORM_SUBMIT = """(selector) => {
    try {
        const el = document.querySelector(selector);
        if (!el) return false;
        const isInsideForm = !!el.closest('form');
        if (!isInsideForm) return false;
        const tag = el.tagName.toUpperCase();
        if (tag === 'INPUT' && el.type === 'submit') return true;
        if (tag === 'BUTTON' && (el.type === 'submit' || !el.hasAttribute('type')))
            return true;
        return false;
    } catch { return false; }
}"""

JS_CHECK_CAPTCHA = """() => {
    try {
        return !!document.querySelector([
            'iframe[src*="recaptcha"]',
            'iframe[src*="captcha"]',
            'iframe[src*="hcaptcha"]',
            'div.g-recaptcha',
            'div[class*="captcha"]',
            '[data-sitekey]',
            'iframe[title*="challenge"]',
            'div[id*="captcha"]'
        ].join(', '));
    } catch { return false; }
}"""

JS_CHECK_2FA = """() => {
    try {
        const otpInputs = document.querySelector([
            'input[autocomplete="one-time-code"]',
            'input[name*="otp"]',
            'input[name*="2fa"]',
            'input[name*="mfa"]',
            'input[name*="verification"]',
            'input[name*="verify"]',
            'input[name*="token"]'
        ].join(', '));
        if (otpInputs) return true;

        const bodyText = document.body?.innerText?.toLowerCase() ?? '';
        const keywords = [
            'two-factor', '2-step', 'verification code',
            'authenticator', 'enter the code'
        ];
        if (keywords.some(kw => bodyText.includes(kw))) return true;

        const singleCharInputs = Array.from(document.querySelectorAll('input'))
            .filter(input => input.maxLength === 1 || input.size === 1);
        if (singleCharInputs.length >= 4 && singleCharInputs.length <= 8)
            return true;

        return false;
    } catch { return false; }
}"""

JS_EXTRACT_BODY_TEXT = """() => {
    return document.body?.innerText ?? '';
}"""

# ── CDPBrowserTool ───────────────────────────────────────────────────


class CDPBrowserTool(BaseTool):
    """Browser automation via CDP connection to remote Chromium.

    Connects to a browserless/chromium Docker container using
    Playwright's connect_over_cdp(). The browser persists independently
    of the agent process — cookies and login sessions survive restarts.
    """

    MAX_CONTENT_LENGTH = 50_000
    ACTION_TIMEOUT_MS = 30_000
    NAVIGATE_TIMEOUT_MS = 60_000
    VIEWPORT = {"width": 1280, "height": 720}
    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 1.0

    def __init__(self, profile_manager: Any | None = None) -> None:
        raw_url = os.environ.get(
            "BROWSER_CDP_URL", "ws://localhost:3000?token=clawbot-dev"
        )
        self._base_cdp_url: str = raw_url
        self._cdp_url: str = raw_url
        self._playwright: Any = None  # Playwright instance
        self._browser: Any = None  # Browser (CDP connection)
        self._contexts: dict[str, Any] = {}  # session_id -> BrowserContext
        self._pages: dict[str, Any] = {}  # session_id -> Page
        self._profile_manager: Any = profile_manager
        self._active_profile: str | None = None
        self._security = BrowserSecurityPolicy()
        self._nav_counts: dict[str, int] = {}  # session_id -> navigation count
        self._current_session_id: str = "default"

        self._action_dispatch: dict[str, Any] = {
            "navigate": self._navigate,
            "click": self._click,
            "type": self._type,
            "extract_text": self._extract_text,
            "screenshot": self._screenshot,
            "scroll": self._scroll,
            "wait_for": self._wait_for,
            "evaluate_js": self._evaluate_js,
            "get_cookies": self._get_cookies,
            "back": self._back,
            "current_url": self._current_url,
            "snapshot": self._snapshot,
            "click_ref": self._click_ref,
            "type_ref": self._type_ref,
            "select_ref": self._select_ref,
        }
        self._login_flow_manager: Any = None

    # ── BaseTool interface ────────────────────────────────────────

    @property
    def name(self) -> str:
        return "browser"

    def set_login_flow_manager(self, manager: Any) -> None:
        """Wire LoginFlowManager after construction (avoids circular init)."""
        self._login_flow_manager = manager
        self._action_dispatch["login"] = self._login

    @property
    def description(self) -> str:
        return (
            "Automate browser interactions for websites without APIs. "
            "PREFERRED WORKFLOW: navigate → snapshot → click_ref/type_ref → snapshot. "
            "The snapshot action returns a numbered list of interactive elements. "
            "Use click_ref(N), type_ref(N, text), select_ref(N, value) to interact by number. "
            "This is more reliable than CSS selectors. Re-snapshot after each action. "
            "Use login action when a site requires authentication (streams browser to user for 2FA/passwords). "
            "Payment pages, form submissions, CAPTCHAs, and 2FA pages "
            "require approval before proceeding."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "action": {
                "type": "string",
                "required": True,
                "description": "The browser action to perform",
                "enum": list(self._action_dispatch.keys()),
            },
            "params": {
                "type": "object",
                "required": True,
                "description": (
                    "Action-specific parameters. "
                    "navigate: {url}. "
                    "click: {selector}. "
                    "type: {selector, text}. "
                    "extract_text: {selector?}. "
                    "screenshot: {full_page?}. "
                    "scroll: {direction?, amount?, selector?}. "
                    "wait_for: {selector, timeout?}. "
                    "evaluate_js: {expression}. "
                    "get_cookies: {}. "
                    "back: {}. "
                    "current_url: {}. "
                    "snapshot: {} — returns numbered interactive elements. "
                    "click_ref: {ref} — click element by snapshot ref number. "
                    "type_ref: {ref, text} — type into element by ref number. "
                    "select_ref: {ref, value} — select option by ref number. "
                    "login: {url} — start interactive login flow (streams to user's phone)."
                ),
            },
            "session_id": {
                "type": "string",
                "required": False,
                "description": (
                    "Optional session ID for isolated browser contexts. "
                    "Default: 'default'"
                ),
            },
            "profile": {
                "type": "string",
                "required": False,
                "description": (
                    "Browser profile name for persistent login sessions. "
                    "Use 'default' for general browsing, or create named profiles "
                    "(e.g., 'gmail', 'work') to keep login sessions separate. "
                    "Default: 'default'"
                ),
            },
        }

    async def execute(
        self,
        action: str = "",
        params: dict[str, Any] | None = None,
        session_id: str = "default",
        profile: str = "default",
        **kwargs: Any,
    ) -> ToolResult:
        """Execute a browser action via remote CDP connection.

        Never raises — always returns a ToolResult.
        """
        if not action:
            return self.fail("Missing required parameter: action")
        if params is None:
            params = {}

        handler = self._action_dispatch.get(action)
        if handler is None:
            return self.fail(
                f"Unknown action '{action}'. "
                f"Available: {', '.join(self._action_dispatch.keys())}"
            )

        # Switch profile if needed
        if self._profile_manager is not None:
            try:
                await self._switch_profile_if_needed(profile)
            except Exception as e:
                return self.fail(f"Profile switch failed: {e}")

        # Connect to browser (lazy / reconnect)
        try:
            await self._ensure_connected()
        except RuntimeError as e:
            return self.fail(str(e))

        # Track current session for use in action handlers
        self._current_session_id = session_id

        # Get or create page for this session
        try:
            page = await self._get_page(session_id)
        except Exception as e:
            return self.fail(f"Failed to create browser context: {e}")

        # Safety checkpoint detection
        try:
            checkpoint = await self._check_checkpoint(page, action, params)
            if checkpoint is not None:
                screenshot_b64 = await self._take_screenshot_safe(page)
                checkpoint_info = json.dumps({
                    "needs_approval": True,
                    "reason": checkpoint["reason"],
                    "checkpoint_type": checkpoint["type"],
                    "screenshot": screenshot_b64,
                })
                return ToolResult(
                    success=False,
                    output=checkpoint_info,
                    error=(
                        f"CHECKPOINT: {checkpoint['reason']}. "
                        "Call request_approval before retrying."
                    ),
                )
        except Exception as e:
            logger.warning("Checkpoint detection error: %s", e)
            # Fail-safe: if detection itself crashes, don't block the action.
            # The checkpoint detector already has internal try/except that
            # returns approval-required on error, so this outer catch handles
            # truly unexpected failures.

        # Execute the action
        try:
            result_data = await handler(page, params)
        except Exception as e:
            logger.exception("Browser action '%s' failed", action)
            return self.fail(f"Browser action '{action}' failed: {e}")

        # Capture screenshot
        screenshot_b64 = await self._take_screenshot_safe(page)

        # Format output
        output_text = json.dumps(result_data, indent=2, default=str)
        output_text = truncate(output_text, 20_000)

        if screenshot_b64:
            output_text += "\n\n[Screenshot captured — visible in tool result]"

        return self.success(output_text)

    # ── Connection management ─────────────────────────────────────

    async def _ensure_connected(self) -> None:
        """Connect to the remote browser via CDP. Reconnects if disconnected.

        Handles the 'browser already running' error that occurs when a
        previous agent session left a stale Chrome instance using the
        same user-data-dir (profile). Recovery: connect without profile
        args, close that browser, then retry with the profile URL.
        """
        if self._browser is not None and self._browser.is_connected():
            return

        # Clean up stale state
        await self._cleanup()

        _import_playwright()

        last_error: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                self._playwright = await _async_playwright().start()
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self._cdp_url
                )
                sanitized_url = self._cdp_url.split("?")[0]
                logger.info(
                    "Connected to browser via CDP: %s (attempt %d)",
                    sanitized_url,
                    attempt + 1,
                )
                return
            except Exception as e:
                last_error = e
                error_msg = str(e).lower()

                # Clean up failed attempt
                if self._playwright:
                    try:
                        await self._playwright.stop()
                    except Exception:
                        pass
                    self._playwright = None
                self._browser = None

                # Recovery: "already running" means a stale Chrome instance
                # is using this profile's user-data-dir. Connect to the base
                # URL (no profile args) to get a fresh browser, which
                # effectively clears the stale lock.
                if "already running" in error_msg and self._cdp_url != self._base_cdp_url:
                    logger.warning(
                        "Stale browser lock detected. Recovering by "
                        "connecting to base URL and resetting profile..."
                    )
                    recovered = await self._recover_stale_browser()
                    if recovered:
                        # Reset profile so next attempt reconnects cleanly
                        self._active_profile = None
                        continue

                delay = self.BASE_RETRY_DELAY * (2 ** attempt)
                logger.warning(
                    "CDP connect attempt %d/%d failed: %s. Retry in %.1fs",
                    attempt + 1,
                    self.MAX_RETRIES,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(
            f"Failed to connect to browser after {self.MAX_RETRIES} attempts: {last_error}"
        )

    async def _recover_stale_browser(self) -> bool:
        """Connect to the base CDP URL and close stale browser contexts.

        Returns True if recovery succeeded and a retry should work.
        """
        pw = None
        browser = None
        try:
            pw = await _async_playwright().start()
            browser = await pw.chromium.connect_over_cdp(self._base_cdp_url)
            # Close all existing contexts to release profile locks
            for ctx in browser.contexts:
                try:
                    await ctx.close()
                except Exception:
                    pass
            logger.info("Recovered: closed stale browser contexts")
            # Reset CDP URL to base so next connection starts clean
            self._cdp_url = self._base_cdp_url
            return True
        except Exception as e:
            logger.warning("Stale browser recovery failed: %s", e)
            return False
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            if pw:
                try:
                    await pw.stop()
                except Exception:
                    pass

    async def _get_page(self, session_id: str) -> Any:
        """Get or create a Page for the given session_id."""
        if session_id in self._pages:
            page = self._pages[session_id]
            if not page.is_closed():
                return page
            # Page was closed externally — clean up
            del self._pages[session_id]
            ctx = self._contexts.pop(session_id, None)
            if ctx:
                try:
                    await ctx.close()
                except Exception:
                    pass

        context = await self._browser.new_context(
            viewport=self.VIEWPORT,
            ignore_https_errors=True,
            permissions=[],
        )
        page = await context.new_page()
        page.set_default_timeout(self.ACTION_TIMEOUT_MS)
        page.set_default_navigation_timeout(self.NAVIGATE_TIMEOUT_MS)

        self._contexts[session_id] = context
        self._pages[session_id] = page
        logger.info("Created browser context for session '%s'", session_id)
        return page

    async def close_context(self, session_id: str = "default") -> None:
        """Close a specific session's context. Keeps browser connection alive."""
        self._pages.pop(session_id, None)
        self._nav_counts.pop(session_id, None)
        ctx = self._contexts.pop(session_id, None)
        if ctx:
            try:
                await ctx.close()
                logger.info("Closed browser context for session '%s'", session_id)
            except Exception:
                pass

    async def shutdown(self) -> None:
        """Clean shutdown — close all contexts and disconnect."""
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Close all contexts, browser connection, and Playwright."""
        for sid in list(self._contexts):
            try:
                await self._contexts[sid].close()
            except Exception:
                pass
        self._contexts.clear()
        self._pages.clear()

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ── Profile management ────────────────────────────────────────────

    async def _switch_profile_if_needed(self, profile: str) -> None:
        """Switch to a different browser profile if needed."""
        if profile == self._active_profile:
            return

        # Ensure profile exists
        if profile == "default":
            self._profile_manager.get_or_create_default()
        else:
            meta = self._profile_manager.get_profile(profile)
            if meta is None:
                raise ValueError(
                    f"Profile '{profile}' not found. "
                    f"Create it first with the browser_profiles tool."
                )

        # Disconnect current browser (if any)
        if self._browser is not None:
            logger.info("Switching profile: %s -> %s", self._active_profile, profile)
            await self._cleanup()

        # Build new CDP URL with profile's user-data-dir
        self._cdp_url = self._build_cdp_url(profile)
        self._active_profile = profile

        # Update last_used timestamp
        self._profile_manager.update_last_used(profile)

    def _build_cdp_url(self, profile_name: str) -> str:
        """Build CDP URL with --user-data-dir launch arg for the given profile."""
        profile_dir = str(self._profile_manager.get_profile_dir(profile_name))
        launch_config = json.dumps({"args": [f"--user-data-dir={profile_dir}"]})

        parsed = urlparse(self._base_cdp_url)
        params = parse_qs(parsed.query)
        params["launch"] = [launch_config]

        new_query = urlencode(params, doseq=True)
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment,
        ))

    # ── Checkpoint detection ──────────────────────────────────────

    async def _check_checkpoint(
        self, page: Any, action: str, params: dict[str, Any]
    ) -> dict[str, str] | None:
        """Detect payment pages, CAPTCHAs, 2FA, and form submissions.

        Returns a dict with {type, reason} if approval needed, None otherwise.
        Ported from server/agent/tools/browser/src/checkpoint.ts.
        """
        try:
            # 1. Payment page detection
            url = page.url.lower()
            url_match = any(
                re.search(p, url, re.IGNORECASE) for p in PAYMENT_URL_PATTERNS
            )
            has_card_fields = await page.evaluate(JS_CHECK_CARD_FIELDS)

            if url_match or has_card_fields:
                return {
                    "type": "payment",
                    "reason": "Payment page detected — approval required before proceeding",
                }

            # 2. Form submission detection (only on click actions)
            if action == "click":
                selector = params.get("selector", "")
                if selector and SUBMIT_TEXT_PATTERN.search(selector):
                    return {
                        "type": "form_submit",
                        "reason": (
                            f'Click on "{selector}" appears to be a form '
                            "submission — approval required"
                        ),
                    }
                if selector:
                    is_form_submit = await page.evaluate(
                        JS_CHECK_FORM_SUBMIT, selector
                    )
                    if is_form_submit:
                        return {
                            "type": "form_submit",
                            "reason": (
                                f'Click on "{selector}" is a form submit '
                                "button — approval required"
                            ),
                        }

            # 3. CAPTCHA detection
            has_captcha = await page.evaluate(JS_CHECK_CAPTCHA)
            if has_captcha:
                return {
                    "type": "captcha",
                    "reason": "CAPTCHA detected — manual intervention or approval required",
                }

            # 4. 2FA detection
            has_2fa = await page.evaluate(JS_CHECK_2FA)
            if has_2fa:
                return {
                    "type": "2fa",
                    "reason": "2FA/MFA verification detected — approval required",
                }

            return None

        except Exception as e:
            logger.warning("Checkpoint detection failed: %s", e)
            return {
                "type": "unknown",
                "reason": "Checkpoint detection failed — approval required as safety fallback",
            }

    # ── Screenshot helper ─────────────────────────────────────────

    @staticmethod
    async def _take_screenshot_safe(page: Any) -> str:
        """Capture viewport screenshot as base64 PNG. Returns empty string on failure."""
        try:
            raw = await page.screenshot(type="png")
            return base64.b64encode(raw).decode("ascii")
        except Exception:
            return ""

    # ── Action handlers ───────────────────────────────────────────
    # Each returns a dict that gets JSON-serialized into the ToolResult output.

    async def _navigate(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url", "")
        if not url:
            return {"success": False, "error": "Missing required parameter: url"}

        # Rate limiting
        session_id = self._current_session_id
        count = self._nav_counts.get(session_id, 0)
        if count >= self._security.MAX_NAVIGATIONS_PER_SESSION:
            return {
                "success": False,
                "error": (
                    f"Navigation limit reached ({self._security.MAX_NAVIGATIONS_PER_SESSION} "
                    f"per session). Close and reopen the session to continue."
                ),
            }

        # Pre-navigation SSRF check (with DNS resolution)
        check = await self._security.check_url_with_dns(url)
        if not check.allowed:
            return {"success": False, "error": f"Blocked: {check.reason}"}

        # Download extension check
        dl_check = self._security.check_download_url(url)
        if not dl_check.allowed:
            return {"success": False, "error": f"Blocked: {dl_check.reason}"}

        # Navigate
        try:
            await page.goto(url, wait_until="networkidle", timeout=self.NAVIGATE_TIMEOUT_MS)
        except Exception:
            # Fallback to domcontentloaded on networkidle timeout
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.NAVIGATE_TIMEOUT_MS)
            except Exception as e:
                return {"success": False, "error": f"Navigation failed: {e}"}

        # Post-redirect SSRF check
        final_url = page.url
        post_check = await self._security.check_url_with_dns(final_url)
        if not post_check.allowed:
            logger.warning(
                "SSRF blocked after redirect: %s -> %s (%s)",
                url, final_url, post_check.reason,
            )
            try:
                await page.goto("about:blank")
            except Exception:
                pass
            return {
                "success": False,
                "error": f"Blocked after redirect: {post_check.reason}",
            }

        # Track navigation count
        self._nav_counts[session_id] = count + 1

        result_data = {
            "success": True,
            "url": page.url,
            "title": await page.title(),
        }

        # Best-effort auth detection for profile domain tracking
        if self._profile_manager and self._active_profile:
            try:
                is_authed = await page.evaluate(JS_CHECK_AUTH_INDICATORS)
                if is_authed:
                    domain = urlparse(page.url).hostname
                    if domain:
                        self._profile_manager.add_authenticated_domain(
                            self._active_profile, domain
                        )
            except Exception:
                pass

        return result_data

    async def _click(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        selector = params.get("selector", "")
        if not selector:
            return {"success": False, "error": "Missing required parameter: selector"}

        try:
            await page.locator(selector).click(timeout=self.ACTION_TIMEOUT_MS)
        except Exception:
            # Fallback: try text-based selector
            try:
                await page.get_by_text(selector).first.click(
                    timeout=self.ACTION_TIMEOUT_MS
                )
            except Exception as e:
                return {"success": False, "error": f"Click failed: {e}"}

        # Short wait for any navigation/network triggered by the click
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        return {
            "success": True,
            "clicked": True,
            "url": page.url,
            "title": await page.title(),
        }

    async def _type(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        selector = params.get("selector", "")
        text = params.get("text", "")
        if not selector:
            return {"success": False, "error": "Missing required parameter: selector"}
        if not text:
            return {"success": False, "error": "Missing required parameter: text"}

        try:
            await page.locator(selector).fill(text, timeout=self.ACTION_TIMEOUT_MS)
        except Exception as e:
            return {"success": False, "error": f"Type failed: {e}"}

        return {"success": True, "typed": True, "selector": selector}

    async def _extract_text(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        selector = params.get("selector")

        try:
            if selector:
                text = await page.locator(selector).inner_text(
                    timeout=self.ACTION_TIMEOUT_MS
                )
            else:
                text = await page.evaluate(JS_EXTRACT_BODY_TEXT)
        except Exception as e:
            return {"success": False, "error": f"Text extraction failed: {e}"}

        truncated = len(text) > self.MAX_CONTENT_LENGTH
        if truncated:
            text = text[: self.MAX_CONTENT_LENGTH]

        return {
            "success": True,
            "text": text,
            "length": len(text),
            "truncated": truncated,
        }

    async def _screenshot(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        full_page = params.get("full_page", False)

        try:
            raw = await page.screenshot(type="png", full_page=full_page)
            b64 = base64.b64encode(raw).decode("ascii")
        except Exception as e:
            return {"success": False, "error": f"Screenshot failed: {e}"}

        return {
            "success": True,
            "format": "png",
            "size_bytes": len(raw),
            "data": b64,
        }

    async def _scroll(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        direction = params.get("direction", "down")
        amount = params.get("amount", 500)
        selector = params.get("selector")

        try:
            if selector:
                await page.locator(selector).scroll_into_view_if_needed(
                    timeout=self.ACTION_TIMEOUT_MS
                )
            else:
                delta_y = amount if direction == "down" else -amount
                await page.evaluate(f"window.scrollBy(0, {delta_y})")
        except Exception as e:
            return {"success": False, "error": f"Scroll failed: {e}"}

        return {"success": True, "direction": direction, "amount": amount}

    async def _wait_for(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        selector = params.get("selector", "")
        timeout = min(params.get("timeout", 10000), self.ACTION_TIMEOUT_MS)

        if not selector:
            return {"success": False, "error": "Missing required parameter: selector"}

        try:
            await page.wait_for_selector(selector, state="visible", timeout=timeout)
        except Exception as e:
            return {"success": False, "error": f"Wait failed: {e}"}

        return {"success": True, "selector": selector, "found": True}

    async def _evaluate_js(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        expression = params.get("expression", "")
        if not expression:
            return {"success": False, "error": "Missing required parameter: expression"}

        # JS size limit
        js_check = self._security.check_js_size(expression)
        if not js_check.allowed:
            return {"success": False, "error": f"Blocked: {js_check.reason}"}

        try:
            result = await page.evaluate(expression)
        except Exception as e:
            return {"success": False, "error": f"JS evaluation failed: {e}"}

        result_str = json.dumps(result, default=str)
        # Response size limit
        max_size = min(self.MAX_CONTENT_LENGTH, self._security.MAX_RESPONSE_SIZE_BYTES)
        if len(result_str) > max_size:
            result_str = result_str[:max_size]
            result = json.loads(result_str + "...")

        return {"success": True, "result": result}

    async def _get_cookies(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        try:
            context = self._contexts.get("default")
            # Find the context for this page
            for sid, p in self._pages.items():
                if p is page:
                    context = self._contexts.get(sid)
                    break
            if context is None:
                return {"success": False, "error": "No browser context found"}
            cookies = await context.cookies()
        except Exception as e:
            return {"success": False, "error": f"Get cookies failed: {e}"}

        return {"success": True, "cookies": cookies}

    async def _back(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        try:
            await page.go_back(timeout=self.NAVIGATE_TIMEOUT_MS)
        except Exception as e:
            return {"success": False, "error": f"Back navigation failed: {e}"}

        return {
            "success": True,
            "url": page.url,
            "title": await page.title(),
        }

    async def _current_url(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": True,
            "url": page.url,
            "title": await page.title(),
        }

    # ── Snapshot / ref-based interaction ──────────────────────

    async def _snapshot(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Walk the DOM and return numbered interactive elements."""
        try:
            result = await page.evaluate(DOM_WALKER_JS)
        except Exception as e:
            return {"success": False, "error": f"Snapshot failed: {e}"}
        return {
            "success": True,
            "snapshot": result.get("snapshot", ""),
            "elementCount": result.get("elementCount", 0),
        }

    async def _resolve_ref(self, page: Any, ref: int) -> dict | None:
        """Look up a snapshot ref from window.__clawbot_refs. Returns entry or None."""
        try:
            return await page.evaluate(JS_LOOKUP_REF, ref)
        except Exception:
            return None

    async def _click_ref(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Click an element by its snapshot ref number."""
        ref = params.get("ref")
        if ref is None:
            return {"success": False, "error": "Missing required parameter: ref"}
        entry = await self._resolve_ref(page, ref)
        if entry is None:
            return {
                "success": False,
                "error": f"Ref [{ref}] not found. Re-run snapshot to get current refs.",
            }
        try:
            locator = page.locator(entry["selector"]).first
            try:
                await locator.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass
            await locator.click(timeout=10_000)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
        except Exception as e:
            return {"success": False, "error": f"Click ref [{ref}] failed: {e}"}
        return {"success": True, "ref": ref, "clicked": entry.get("description", "")}

    async def _type_ref(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Type text into an element by its snapshot ref number."""
        ref = params.get("ref")
        text = params.get("text", "")
        if ref is None:
            return {"success": False, "error": "Missing required parameter: ref"}
        if not text:
            return {"success": False, "error": "Missing required parameter: text"}
        entry = await self._resolve_ref(page, ref)
        if entry is None:
            return {
                "success": False,
                "error": f"Ref [{ref}] not found. Re-run snapshot to get current refs.",
            }
        try:
            locator = page.locator(entry["selector"]).first
            try:
                await locator.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass
            await locator.fill("")
            await locator.type(text, delay=50)
        except Exception as e:
            return {"success": False, "error": f"Type into ref [{ref}] failed: {e}"}
        return {"success": True, "ref": ref, "typed": entry.get("description", "")}

    async def _select_ref(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Select an option in a dropdown by its snapshot ref number."""
        ref = params.get("ref")
        value = params.get("value", "")
        if ref is None:
            return {"success": False, "error": "Missing required parameter: ref"}
        if not value:
            return {"success": False, "error": "Missing required parameter: value"}
        entry = await self._resolve_ref(page, ref)
        if entry is None:
            return {
                "success": False,
                "error": f"Ref [{ref}] not found. Re-run snapshot to get current refs.",
            }
        try:
            locator = page.locator(entry["selector"]).first
            await locator.select_option(value=value, timeout=10_000)
        except Exception as e:
            return {"success": False, "error": f"Select ref [{ref}] failed: {e}"}
        return {"success": True, "ref": ref, "selected": value}

    # ── Login flow action ─────────────────────────────────────

    async def _login(self, page: Any, params: dict[str, Any]) -> dict[str, Any]:
        """Start interactive login flow (streams browser to user's phone)."""
        if self._login_flow_manager is None:
            return {"success": False, "error": "Login flow manager not configured."}
        url = params.get("url", "")
        if not url:
            return {"success": False, "error": "Missing required parameter: url"}
        profile = self._active_profile or "default"
        interval_ms = params.get("interval_ms", 1500)
        return await self._login_flow_manager.start_login_flow(
            profile=profile, url=url, interval_ms=interval_ms,
        )
