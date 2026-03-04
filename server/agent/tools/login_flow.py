"""
ClawBot Login Flow Manager

Manages interactive browser login sessions with screenshot streaming.
The user watches the browser on their iOS device and can type text
(passwords, 2FA codes) or click elements to complete authentication.

Delegates to CDPBrowserTool for browser automation and BrowserProfileManager
for persistent profile/session management. Does NOT own a browser connection.

Design reference: OpenClaw's noVNC pattern — but mobile-native via
JPEG screenshot streaming over existing WebSocket connection.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from server.agent.tools.browser_js import DOM_WALKER_JS, JS_LOOKUP_REF, JS_CHECK_AUTH_INDICATORS

logger = logging.getLogger(__name__)


class LoginFlowManager:
    """Manages interactive login sessions with screenshot streaming."""

    def __init__(
        self,
        browser_tool: Any,  # CDPBrowserTool
        gateway_client: Any,  # GatewayClient
        profile_manager: Any,  # BrowserProfileManager
    ) -> None:
        self._browser = browser_tool
        self._gateway = gateway_client
        self._profiles = profile_manager
        self._active_flows: dict[str, asyncio.Task] = {}  # profile -> streaming task
        self._flow_sessions: dict[str, str] = {}  # profile -> session_id

    async def start_login_flow(
        self, profile: str, url: str, interval_ms: int = 1500,
    ) -> dict:
        """Start an interactive login flow with screenshot streaming.

        Navigates to the given URL using the specified browser profile,
        then begins streaming JPEG screenshots + DOM snapshots to iOS
        at the given interval.

        Args:
            profile: Browser profile name (e.g. "gmail", "default").
            url: The login page URL to navigate to.
            interval_ms: Screenshot interval in milliseconds (default 1500).

        Returns:
            {"success": True, "profile": ..., "url": ...} on success,
            or {"success": False, "error": ...} on failure.
        """
        # Validate profile exists
        if profile == "default":
            self._profiles.get_or_create_default()
        else:
            meta = self._profiles.get_profile(profile)
            if meta is None:
                return {
                    "success": False,
                    "error": (
                        f"Profile '{profile}' not found. "
                        "Create it first with the browser_profiles tool."
                    ),
                }

        # Cancel any existing flow for this profile
        if profile in self._active_flows:
            self._active_flows[profile].cancel()
            try:
                await self._active_flows[profile]
            except (asyncio.CancelledError, Exception):
                pass
            del self._active_flows[profile]

        # Use a dedicated session_id for login flows
        session_id = f"login-{profile}"
        self._flow_sessions[profile] = session_id

        # Navigate to the login URL via the browser tool
        # (this handles SSRF checks, profile switching, CDP connect)
        result = await self._browser.execute(
            action="navigate",
            params={"url": url},
            session_id=session_id,
            profile=profile,
        )
        if not result.success:
            return {
                "success": False,
                "error": f"Navigation failed: {result.error or result.output}",
            }

        # Start background screenshot streaming task
        task = asyncio.create_task(
            self._screenshot_loop(profile, session_id, interval_ms),
        )
        self._active_flows[profile] = task

        logger.info(
            "Login flow started: profile=%s url=%s interval=%dms",
            profile, url, interval_ms,
        )
        return {"success": True, "profile": profile, "url": url}

    async def _screenshot_loop(
        self, profile: str, session_id: str, interval_ms: int,
    ) -> None:
        """Background task that streams screenshots + DOM snapshots to iOS."""
        try:
            while True:
                page = self._browser._pages.get(session_id)
                if page is None or page.is_closed():
                    logger.info(
                        "Login flow page closed for profile '%s'", profile,
                    )
                    break

                try:
                    # JPEG screenshot (quality=60 keeps frames ~50-80KB)
                    raw = await page.screenshot(type="jpeg", quality=60)
                    image_b64 = base64.b64encode(raw).decode("ascii")

                    # DOM snapshot for element refs
                    await page.evaluate(DOM_WALKER_JS)

                    # Extract element rects from window.__clawbot_refs
                    elements = await page.evaluate("""() => {
                        const refs = window.__clawbot_refs || {};
                        return Object.entries(refs).map(([ref, entry]) => ({
                            ref: parseInt(ref),
                            tag: entry.tagName,
                            type: null,
                            text: entry.description.slice(0, 50),
                            rect: entry.rect
                        }));
                    }""")

                    await self._gateway.emit_event("browser/login:frame", {
                        "imageBase64": image_b64,
                        "url": page.url,
                        "profile": profile,
                        "pageTitle": await page.title(),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "elements": elements,
                    })

                except Exception as e:
                    logger.warning(
                        "Screenshot loop error for profile '%s': %s",
                        profile, e,
                    )
                    break

                await asyncio.sleep(interval_ms / 1000)

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(
                "Screenshot loop crashed for profile '%s': %s", profile, e,
            )

    async def send_login_input(
        self, profile: str, ref: int, text: str,
    ) -> dict:
        """Type text into a referenced element during a login flow.

        Args:
            profile: Browser profile with an active login flow.
            ref: Element reference number from the DOM snapshot.
            text: Text to type (password, 2FA code, etc.).

        Returns:
            {"success": True, "ref": ...} on success,
            or {"success": False, "error": ...} on failure.
        """
        session_id = self._flow_sessions.get(profile)
        if session_id is None:
            return {
                "success": False,
                "error": f"No active login flow for profile '{profile}'.",
            }

        page = self._browser._pages.get(session_id)
        if page is None or page.is_closed():
            return {
                "success": False,
                "error": f"Login page closed for profile '{profile}'.",
            }

        # Look up the ref from window.__clawbot_refs
        entry = await page.evaluate(JS_LOOKUP_REF, ref)
        if entry is None:
            return {
                "success": False,
                "error": (
                    f"Ref [{ref}] not found. The page may have changed "
                    "since the last snapshot."
                ),
            }

        try:
            locator = page.locator(entry["selector"]).first
            try:
                await locator.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass  # best-effort scroll
            await locator.fill("")
            await locator.type(text, delay=50)  # 50ms delay for key handlers
        except Exception as e:
            return {
                "success": False,
                "error": f"Type into ref [{ref}] failed: {e}",
            }

        return {"success": True, "ref": ref}

    async def click_login_element(
        self, profile: str, ref: int,
    ) -> dict:
        """Click an element during a login flow.

        Args:
            profile: Browser profile with an active login flow.
            ref: Element reference number from the DOM snapshot.

        Returns:
            {"success": True, "ref": ...} on success,
            or {"success": False, "error": ...} on failure.
        """
        session_id = self._flow_sessions.get(profile)
        if session_id is None:
            return {
                "success": False,
                "error": f"No active login flow for profile '{profile}'.",
            }

        page = self._browser._pages.get(session_id)
        if page is None or page.is_closed():
            return {
                "success": False,
                "error": f"Login page closed for profile '{profile}'.",
            }

        # Look up the ref from window.__clawbot_refs
        entry = await page.evaluate(JS_LOOKUP_REF, ref)
        if entry is None:
            return {
                "success": False,
                "error": (
                    f"Ref [{ref}] not found. The page may have changed "
                    "since the last snapshot."
                ),
            }

        try:
            locator = page.locator(entry["selector"]).first
            try:
                await locator.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass  # best-effort scroll
            await locator.click(timeout=10_000)
            try:
                await page.wait_for_load_state(
                    "domcontentloaded", timeout=5000,
                )
            except Exception:
                pass  # best-effort wait
        except Exception as e:
            return {
                "success": False,
                "error": f"Click ref [{ref}] failed: {e}",
            }

        return {"success": True, "ref": ref}

    async def stop_login_flow(self, profile: str) -> dict:
        """Stop a login flow and check authentication status.

        Cancels the screenshot streaming task, checks whether the
        browser is now authenticated (via auth indicators), records
        the domain if so, and emits a login:end event.

        Args:
            profile: Browser profile whose login flow to stop.

        Returns:
            {"success": True, "authenticated": bool, "domain": str}
        """
        # Cancel streaming task
        task = self._active_flows.pop(profile, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        session_id = self._flow_sessions.pop(profile, None)
        authenticated = False
        domain = ""

        if session_id is not None:
            page = self._browser._pages.get(session_id)
            if page is not None and not page.is_closed():
                # Check for auth indicators
                try:
                    authenticated = await page.evaluate(
                        JS_CHECK_AUTH_INDICATORS,
                    )
                except Exception:
                    pass

                # Extract domain from current URL
                try:
                    parsed = urlparse(page.url)
                    domain = parsed.hostname or ""
                except Exception:
                    pass

                # Record authenticated domain in profile
                if authenticated and domain:
                    self._profiles.add_authenticated_domain(profile, domain)

        # Emit login:end event
        await self._gateway.emit_event("browser/login:end", {
            "profile": profile,
            "authenticated": authenticated,
            "domain": domain,
        })

        logger.info(
            "Login flow stopped: profile=%s authenticated=%s domain=%s",
            profile, authenticated, domain,
        )
        return {
            "success": True,
            "authenticated": authenticated,
            "domain": domain,
        }

    async def shutdown(self) -> None:
        """Cancel all active login flows."""
        for profile in list(self._active_flows):
            task = self._active_flows.pop(profile)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._flow_sessions.clear()
        logger.info("LoginFlowManager shut down — all flows cancelled")
