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

from server.agent.tools.browser_cdp import JS_CHECK_AUTH_INDICATORS

logger = logging.getLogger(__name__)


# ── JS constants ──────────────────────────────────────────────
# DOM_WALKER_JS: exact copy from browser/src/snapshot.ts lines 39-306.
# Walks the DOM, produces [N] element "text" format, stores refs
# on window.__clawbot_refs with {selector, tagName, description, rect}.
# This is the SAME JS the snapshot.ts sidecar uses — we call it
# directly via page.evaluate() from Playwright (no Node process needed).

DOM_WALKER_JS = """(function buildSnapshot() {
  var MAX_SNAPSHOT_CHARS = 6000;
  var MAX_OPTIONS = 10;
  var MAX_HREF_CHARS = 80;
  var MAX_TEXT_CHARS = 60;
  var PAGE_TEXT_CHARS = 2000;

  var INTERACTIVE_SELECTORS = [
    'a[href]', 'button', 'input', 'select', 'textarea',
    '[role="button"]', '[role="link"]', '[role="checkbox"]',
    '[role="tab"]', '[role="menuitem"]', '[role="switch"]',
    '[onclick]'
  ];

  var refs = {};
  var refCounter = 0;

  // --- Visibility check ---
  function isVisible(el) {
    try {
      if (el.getAttribute('aria-hidden') === 'true') return false;
      var style = window.getComputedStyle(el);
      if (style.display === 'none') return false;
      if (style.visibility === 'hidden') return false;
      if (parseFloat(style.opacity) === 0) return false;
      var rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return false;
      if (rect.bottom < -100 || rect.top > window.innerHeight * 2) return false;
      if (rect.right < -100 || rect.left > window.innerWidth * 2) return false;
      return true;
    } catch (e) {
      return false;
    }
  }

  // --- Check if element is inside a hidden ancestor ---
  function hasHiddenAncestor(el) {
    var node = el.parentElement;
    while (node && node !== document.body) {
      try {
        var style = window.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return true;
        if (node.getAttribute('aria-hidden') === 'true') return true;
      } catch (e) {
        return false;
      }
      node = node.parentElement;
    }
    return false;
  }

  // --- Unique selector generator ---
  function getSelector(el) {
    if (el.id) return '#' + CSS.escape(el.id);
    var parts = [];
    var node = el;
    while (node && node !== document.body && node !== document.documentElement) {
      var seg = node.tagName.toLowerCase();
      if (node.id) {
        parts.unshift('#' + CSS.escape(node.id));
        break;
      }
      var parent = node.parentElement;
      if (parent) {
        var siblings = Array.from(parent.children).filter(function(c) {
          return c.tagName === node.tagName;
        });
        if (siblings.length > 1) {
          var idx = siblings.indexOf(node) + 1;
          seg += ':nth-of-type(' + idx + ')';
        }
      }
      parts.unshift(seg);
      node = node.parentElement;
    }
    return parts.join(' > ') || el.tagName.toLowerCase();
  }

  // --- Get label for an input/textarea ---
  function getLabel(el) {
    // 1. aria-label
    var aria = el.getAttribute('aria-label');
    if (aria) return aria;
    // 2. aria-labelledby
    var labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      var labelEl = document.getElementById(labelledBy);
      if (labelEl) return (labelEl.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
    }
    // 3. Associated <label>
    if (el.id) {
      var label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (label) return (label.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
    }
    // 4. Wrapping <label>
    var parentLabel = el.closest('label');
    if (parentLabel) {
      var text = (parentLabel.textContent || '').trim();
      if (text.length > 0) return text.substring(0, MAX_TEXT_CHARS);
    }
    // 5. placeholder
    if (el.placeholder) return el.placeholder;
    // 6. name attribute
    if (el.name) return el.name;
    return '';
  }

  // --- Escape quotes in strings ---
  function esc(s) {
    return (s || '').replace(/"/g, '\\\\"');
  }

  // --- Gather candidates ---
  var selectorStr = INTERACTIVE_SELECTORS.join(', ');
  var candidateSet = new Set();
  var rawCandidates = document.querySelectorAll(selectorStr);
  for (var i = 0; i < rawCandidates.length; i++) {
    candidateSet.add(rawCandidates[i]);
  }

  // Also find cursor:pointer elements not already matched
  var allDivLike = document.querySelectorAll('div, span, li, article, section, td, tr');
  for (var i = 0; i < allDivLike.length; i++) {
    var el = allDivLike[i];
    try {
      if (window.getComputedStyle(el).cursor === 'pointer' && !candidateSet.has(el)) {
        candidateSet.add(el);
      }
    } catch (e) {}
  }

  var candidates = Array.from(candidateSet);

  // Filter visible + no hidden ancestor
  candidates = candidates.filter(function(el) {
    return isVisible(el) && !hasHiddenAncestor(el);
  });

  // Sort by document position (DOM order)
  candidates.sort(function(a, b) {
    var pos = a.compareDocumentPosition(b);
    if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
    if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
    return 0;
  });

  // --- Build snapshot lines ---
  var lines = [];
  var title = document.title || '(untitled)';
  var url = window.location.href;
  lines.push('[Page] ' + title);
  lines.push('[URL] ' + url);
  lines.push('');

  for (var c = 0; c < candidates.length; c++) {
    var el = candidates[c];
    refCounter++;
    var ref = String(refCounter);
    var tag = el.tagName.toLowerCase();
    var rect = el.getBoundingClientRect();
    var selector = getSelector(el);
    var aria = el.getAttribute('aria-label') || '';
    var description = '';
    var line = '[' + ref + '] ';

    if (tag === 'input') {
      var type = (el.type || 'text').toLowerCase();
      var label = getLabel(el);
      var val = el.value || '';
      line += 'input';
      if (type !== 'text') line += '[' + type + ']';
      line += ' "' + esc(label) + '"';
      if (val) line += ' value="' + esc(val) + '"';
      description = 'input ' + label;
    } else if (tag === 'select') {
      var label = getLabel(el);
      var selected = (el.options && el.options[el.selectedIndex])
        ? el.options[el.selectedIndex].text : '';
      var opts = [];
      var optCount = el.options ? el.options.length : 0;
      for (var oi = 0; oi < Math.min(optCount, MAX_OPTIONS); oi++) {
        opts.push('"' + esc(el.options[oi].text) + '"');
      }
      line += 'select "' + esc(label) + '" value="' + esc(selected) + '"';
      line += ' options=[' + opts.join(',') + ']';
      if (optCount > MAX_OPTIONS) line += ' +' + (optCount - MAX_OPTIONS) + ' more';
      description = 'select ' + label;
    } else if (tag === 'textarea') {
      var label = getLabel(el);
      var val = (el.value || '').substring(0, 100);
      line += 'textarea "' + esc(label) + '"';
      if (val) line += ' value="' + esc(val) + '"';
      description = 'textarea ' + label;
    } else if (tag === 'a') {
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      var href = (el.getAttribute('href') || '').substring(0, MAX_HREF_CHARS);
      line += 'link "' + esc(text) + '"';
      if (aria && aria !== text) line += ' aria="' + esc(aria) + '"';
      line += ' -> ' + href;
      description = 'link ' + text;
    } else if (tag === 'button' || el.getAttribute('role') === 'button') {
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      line += 'button "' + esc(text) + '"';
      if (aria && aria !== text) line += ' aria="' + esc(aria) + '"';
      description = 'button ' + text;
    } else if (el.getAttribute('role') === 'checkbox') {
      var label = aria || (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      var checked = el.getAttribute('aria-checked') === 'true' || el.checked;
      line += 'checkbox "' + esc(label) + '"';
      if (checked) line += ' [checked]';
      description = 'checkbox ' + label;
    } else if (el.getAttribute('role') === 'tab') {
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      var selected = el.getAttribute('aria-selected') === 'true';
      line += 'tab "' + esc(text) + '"';
      if (selected) line += ' [selected]';
      description = 'tab ' + text;
    } else if (el.getAttribute('role') === 'link') {
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      line += 'link "' + esc(text) + '"';
      if (aria && aria !== text) line += ' aria="' + esc(aria) + '"';
      description = 'link ' + text;
    } else {
      // Generic clickable element (div, span, etc.)
      var text = (el.textContent || '').trim().substring(0, MAX_TEXT_CHARS);
      line += tag + ' "' + esc(text) + '"';
      if (aria) line += ' aria="' + esc(aria) + '"';
      description = tag + ' ' + text;
    }

    refs[ref] = {
      selector: selector,
      tagName: tag,
      description: description,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
    };

    lines.push(line);

    // Check total size — leave room for page text section
    var currentLength = lines.join('\\n').length;
    if (currentLength > MAX_SNAPSHOT_CHARS - PAGE_TEXT_CHARS - 200) {
      var remaining = candidates.length - refCounter;
      if (remaining > 0) {
        lines.push('... [' + remaining + ' more interactive elements]');
      }
      break;
    }
  }

  // --- Page text section (above fold) ---
  lines.push('');
  lines.push('--- Page Text (above fold) ---');
  var bodyText = (document.body && document.body.innerText) ? document.body.innerText : '';
  var pageText = bodyText.substring(0, PAGE_TEXT_CHARS).replace(/\\n{3,}/g, '\\n\\n').trim();
  lines.push(pageText);

  // --- Store refs globally ---
  window.__clawbot_refs = refs;

  // --- Final truncation ---
  var snapshot = lines.join('\\n');
  if (snapshot.length > MAX_SNAPSHOT_CHARS) {
    snapshot = snapshot.substring(0, MAX_SNAPSHOT_CHARS) + '\\n... [snapshot truncated]';
  }

  return { snapshot: snapshot, elementCount: refCounter };
})()"""

# Ref lookup — same pattern as snapshot.ts:350-356
JS_LOOKUP_REF = """(ref) => {
    const refs = window.__clawbot_refs;
    if (!refs) return null;
    return refs[String(ref)] || null;
}"""


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
