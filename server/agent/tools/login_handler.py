"""
ClawBot Login Handler — 3-Step Authentication Fallback Chain

When the agent hits a login wall during browser automation, this module
orchestrates authentication through a prioritized fallback chain:

  Step 1: Inject cached session cookies (fastest, no user interaction)
  Step 2: Request credentials from iOS → auto-fill login form
  Step 3: Interactive login flow (user authenticates on their phone)

Security:
  - Credential references nil'd in finally block immediately after injection
  - Session cache stores ONLY cookies, never credentials
  - No credential values in log output
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from server.agent.tools.browser_js import JS_CHECK_AUTH_INDICATORS
from server.agent.tools.browser_cdp import (
    JS_CHECK_2FA,
    JS_CHECK_CAPTCHA,
    JS_DETECT_LOGIN_FORM,
)
from server.agent.tools.credential_manager import CredentialManager
from server.agent.tools.session_cache import SessionCache

logger = logging.getLogger(__name__)

# ── Known login URLs for common domains ─────────────────────

_LOGIN_URLS: dict[str, str] = {
    "amazon.com": "https://www.amazon.com/ap/signin",
    "www.amazon.com": "https://www.amazon.com/ap/signin",
    "stockx.com": "https://stockx.com/login",
    "www.stockx.com": "https://stockx.com/login",
    "goat.com": "https://www.goat.com/login",
    "www.goat.com": "https://www.goat.com/login",
    "nike.com": "https://www.nike.com/login",
    "www.nike.com": "https://www.nike.com/login",
    "ebay.com": "https://signin.ebay.com",
    "www.ebay.com": "https://signin.ebay.com",
    "walmart.com": "https://www.walmart.com/account/login",
    "www.walmart.com": "https://www.walmart.com/account/login",
    "target.com": "https://www.target.com/login",
    "www.target.com": "https://www.target.com/login",
    "grailed.com": "https://www.grailed.com/login",
    "www.grailed.com": "https://www.grailed.com/login",
    "footlocker.com": "https://www.footlocker.com/login",
    "www.footlocker.com": "https://www.footlocker.com/login",
    "bestbuy.com": "https://www.bestbuy.com/identity/signin",
    "www.bestbuy.com": "https://www.bestbuy.com/identity/signin",
}


class LoginHandler:
    """3-step authentication fallback chain for login walls.

    Step 1: Inject cached session cookies
    Step 2: Request credentials from iOS → auto-fill login form
    Step 3: Interactive login flow (user authenticates on phone)

    Usage::

        handler = LoginHandler(browser, cred_manager, cache, login_flow, profiles)
        authenticated = await handler.handle_login_wall(page, "accounts.google.com")
    """

    def __init__(
        self,
        browser_tool: Any,
        credential_manager: CredentialManager,
        session_cache: SessionCache,
        login_flow_manager: Any,
        profile_manager: Any,
    ) -> None:
        self._browser = browser_tool
        self._cred_manager = credential_manager
        self._session_cache = session_cache
        self._login_flow = login_flow_manager
        self._profiles = profile_manager

    async def handle_login_wall(
        self,
        page: Any,
        domain: str,
        profile: str = "default",
        session_id: str = "default",
        reason: str = "",
    ) -> bool:
        """Attempt to authenticate past a login wall.

        Tries three strategies in order, returning True on the first success.

        Args:
            page: The Playwright page currently showing a login wall.
            domain: The domain to authenticate against.
            profile: Browser profile name for cookie/session persistence.
            session_id: Browser session ID for context lookup.
            reason: Why login is needed (shown to user in step 2).

        Returns:
            True if authenticated successfully, False if all steps failed.
        """
        # Step 1: Try cached session cookies
        logger.info("LoginHandler step 1: checking session cache for domain=%s", domain)
        if await self._try_cached_session(page, domain, session_id):
            logger.info("LoginHandler: authenticated via cached session for domain=%s", domain)
            self._record_auth(profile, domain)
            return True

        # Step 2: Request credentials from iOS
        logger.info("LoginHandler step 2: requesting credentials for domain=%s", domain)
        if await self._try_ios_credentials(page, domain, profile, session_id, reason):
            logger.info("LoginHandler: authenticated via iOS credentials for domain=%s", domain)
            self._record_auth(profile, domain)
            await self._save_session_cookies(page, domain, session_id)
            return True

        # Step 3: Interactive login flow
        logger.info("LoginHandler step 3: starting interactive login for domain=%s", domain)
        if await self._try_interactive_login(page, domain, profile):
            logger.info("LoginHandler: authenticated via interactive login for domain=%s", domain)
            return True

        logger.warning("LoginHandler: all authentication methods failed for domain=%s", domain)
        return False

    # ── Step 1: Cached Session Cookies ─────────────────────────

    async def _try_cached_session(
        self, page: Any, domain: str, session_id: str,
    ) -> bool:
        """Inject cached cookies and check if session is still valid."""
        cookies = await self._session_cache.load_session(domain)
        if not cookies:
            return False

        context = self._browser._contexts.get(session_id)
        if context is None:
            return False

        try:
            await context.add_cookies(cookies)
            await page.reload(wait_until="domcontentloaded", timeout=15_000)
            await asyncio.sleep(1)

            is_auth = await page.evaluate(JS_CHECK_AUTH_INDICATORS)
            if is_auth:
                return True

            # Cookies didn't work — clear the stale cache
            await self._session_cache.clear_session(domain)
            return False

        except Exception as e:
            logger.warning(
                "Session cookie injection failed for domain=%s: %s", domain, e,
            )
            await self._session_cache.clear_session(domain)
            return False

    # ── Step 2: iOS Credentials → Auto-fill ────────────────────

    async def _try_ios_credentials(
        self,
        page: Any,
        domain: str,
        profile: str,
        session_id: str,
        reason: str,
    ) -> bool:
        """Request credentials from iOS and use them to auto-fill the login form."""
        if self._cred_manager is None:
            return False

        cred_reason = reason or f"Login required for {domain}"
        credentials = await self._cred_manager.request_credentials(domain, cred_reason)
        if not credentials:
            return False

        cred = credentials[0]
        username = cred.get("username", "")
        password = cred.get("password", "")

        try:
            # Detect login form
            form_info = await page.evaluate(JS_DETECT_LOGIN_FORM)
            if not form_info.get("hasUsername") and not form_info.get("hasPassword"):
                return False

            username_sel = form_info.get("usernameSelector")
            password_sel = form_info.get("passwordSelector")
            submit_sel = form_info.get("submitSelector")

            # Auto-fill username
            if username_sel and username:
                locator = page.locator(username_sel).first
                await locator.fill("", timeout=5000)
                await locator.type(username, delay=30, timeout=10_000)

            # Handle multi-step login (username → next → password)
            if not password_sel and submit_sel:
                await page.locator(submit_sel).first.click(timeout=10_000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass
                await asyncio.sleep(1)
                form_info = await page.evaluate(JS_DETECT_LOGIN_FORM)
                password_sel = form_info.get("passwordSelector")
                submit_sel = form_info.get("submitSelector")

            # Auto-fill password
            if password_sel and password:
                locator = page.locator(password_sel).first
                await locator.fill("", timeout=5000)
                await locator.type(password, delay=30, timeout=10_000)
            elif not password_sel:
                return False

            # Click submit
            if submit_sel:
                await page.locator(submit_sel).first.click(timeout=10_000)
            else:
                await page.keyboard.press("Enter")

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass
            await asyncio.sleep(2)

        except Exception as e:
            logger.warning("Auto-fill with iOS credentials failed: %s", e)
            return False
        finally:
            # SECURITY: nil credential references immediately
            credentials = None  # noqa: F841
            cred = None  # noqa: F841
            username = None  # noqa: F841
            password = None  # noqa: F841

        # Check for 2FA / CAPTCHA after credential submission
        try:
            has_2fa = await page.evaluate(JS_CHECK_2FA)
            has_captcha = await page.evaluate(JS_CHECK_CAPTCHA)
        except Exception:
            has_2fa = False
            has_captcha = False

        if has_2fa or has_captcha:
            logger.info(
                "2FA/CAPTCHA detected after credential submission for domain=%s, "
                "opening Browser Login sheet on current page: %s",
                domain, page.url,
            )
            # Open Browser Login sheet on the CURRENT page (the 2FA/CAPTCHA page).
            # Do NOT fall through to Step 3 — it would navigate away from
            # the 2FA page and send the user back to the login form.
            if self._login_flow is not None:
                try:
                    result = await self._login_flow.start_login_flow(
                        profile=profile, url=page.url, interval_ms=1500,
                    )
                    if result.get("success"):
                        logger.info("2FA completed via Browser Login sheet for domain=%s", domain)
                        await self._save_session_cookies(page, domain, session_id)
                        return True
                    # User may have completed 2FA even if flow didn't report success
                    try:
                        if await page.evaluate(JS_CHECK_AUTH_INDICATORS):
                            await self._save_session_cookies(page, domain, session_id)
                            return True
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("Browser Login sheet for 2FA failed: %s", e)
            # No login flow manager or it failed — fall to step 3
            return False

        # Check authentication
        try:
            return bool(await page.evaluate(JS_CHECK_AUTH_INDICATORS))
        except Exception:
            return False

    # ── Step 3: Interactive Login Flow ─────────────────────────

    async def _try_interactive_login(
        self, page: Any, domain: str, profile: str,
    ) -> bool:
        """Start interactive login flow (streams browser to user's phone).

        Uses a 3-step URL fallback to ensure the user sees a login form,
        not a homepage:
          A. Find a sign-in link on the current page
          B. Use a known login URL for the domain
          C. Fall back to the domain root
        """
        if self._login_flow is None:
            logger.warning("No login flow manager available")
            return False

        try:
            url = page.url if page else None

            # Step A: Try to find a sign-in link on the current page
            if url and url != "about:blank":
                try:
                    sign_in_link = await page.evaluate("""() => {
                        const links = Array.from(document.querySelectorAll('a'));
                        const signIn = links.find(a => {
                            const t = (a.textContent || '').toLowerCase().trim();
                            return /^sign.?in$|^log.?in$|^my account$|^account$/i.test(t);
                        });
                        return signIn ? signIn.href : null;
                    }""")
                    if sign_in_link:
                        logger.info("Found sign-in link: %s", sign_in_link)
                        url = sign_in_link
                except Exception:
                    pass

            # Step B: If no link found, use known login URL for domain
            if not url or url == "about:blank" or url == page.url:
                url = self.get_login_url(domain)

            # Step C: Final fallback
            if not url or url == "about:blank":
                url = f"https://{domain}"

            logger.info("Starting interactive login for domain=%s url=%s", domain, url)
            result = await self._login_flow.start_login_flow(
                profile=profile, url=url, interval_ms=1500,
            )
            return result.get("success", False)
        except Exception as e:
            logger.warning("Interactive login flow failed: %s", e)
            return False

    # ── Public Utilities ─────────────────────────────────────

    def get_login_url(self, domain: str) -> str:
        """Get known login URL for domain, or smart default."""
        clean = domain.lower().strip()
        if clean in _LOGIN_URLS:
            return _LOGIN_URLS[clean]
        no_www = clean.removeprefix("www.")
        if no_www in _LOGIN_URLS:
            return _LOGIN_URLS[no_www]
        return f"https://{clean}/login"

    async def pre_warm_auth(self, domain: str, profile: str = "default") -> dict:
        """Pre-fetch credentials for domain. No browser needed."""
        logger.info("Pre-warming auth for domain=%s", domain)

        # Check session cache first
        if self._session_cache:
            cached = await self._session_cache.load_session(domain)
            if cached:
                logger.info("Pre-warm: session cache HIT for %s", domain)
                return {"status": "cached", "domain": domain}

        # Try to get credentials from iOS
        try:
            creds = await self._cred_manager.request_credentials(
                domain, f"Pre-warming credentials for {domain}",
            )
            if creds:
                logger.info(
                    "Pre-warm: got %d credential(s) for %s",
                    len(creds) if isinstance(creds, list) else 1,
                    domain,
                )
                return {"status": "credentials_ready", "domain": domain}
            else:
                logger.info("Pre-warm: no credentials for %s", domain)
                return {"status": "no_credentials", "domain": domain}
        except Exception as e:
            logger.warning("Pre-warm failed for %s: %s", domain, e)
            return {"status": "error", "domain": domain, "error": str(e)}

    async def detect_login_wall(self, page: Any) -> bool:
        """Check if current page is a login wall."""
        try:
            result = await page.evaluate("""() => {
                const url = location.href.toLowerCase();
                const urlHasLogin = /\\/login|\\/signin|\\/auth|\\/ap\\/signin|\\/sso/.test(url);

                const hasPwField = !!document.querySelector('input[type="password"]:not([hidden])');

                const bodyText = (document.body?.innerText || '').toLowerCase().slice(0, 2000);
                const hasLoginText = /sign in to continue|please (log|sign) in|create an account or sign in/.test(bodyText);

                return urlHasLogin || hasPwField || hasLoginText;
            }""")
            return bool(result)
        except Exception:
            return False

    # ── Helpers ────────────────────────────────────────────────

    async def _save_session_cookies(
        self, page: Any, domain: str, session_id: str,
    ) -> None:
        """Save current browser cookies for this domain to the session cache."""
        context = self._browser._contexts.get(session_id)
        if context is None:
            return
        try:
            all_cookies = await context.cookies()
            domain_cookies = [
                c for c in all_cookies
                if domain in (c.get("domain", "").lstrip("."))
                or c.get("domain", "").lstrip(".").endswith("." + domain)
            ]
            if domain_cookies:
                await self._session_cache.save_session(domain, domain_cookies)
                logger.info(
                    "Saved %d session cookies for domain=%s",
                    len(domain_cookies), domain,
                )
        except Exception as e:
            logger.warning(
                "Failed to save session cookies for domain=%s: %s", domain, e,
            )

    def _record_auth(self, profile: str, domain: str) -> None:
        """Record authenticated domain in the browser profile."""
        if self._profiles and domain:
            try:
                self._profiles.add_authenticated_domain(profile, domain)
            except Exception:
                pass
