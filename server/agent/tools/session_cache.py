"""
ClawBot Session Cache — Browser Cookie Persistence

Persists Playwright browser cookies per domain so the agent can resume
authenticated sessions without re-entering credentials.

Storage: JSON files at /workspace/data/sessions/{domain}.json
Contains ONLY cookies — NEVER usernames, passwords, or other credentials.

Security:
  - Session files have 0o600 permissions (owner read/write only)
  - Domain names sanitized to prevent path traversal
  - Expired cookies filtered out on load
  - No credential values ever written to disk
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Domain validation: lowercase alphanumeric + dots + hyphens, 1-254 chars
DOMAIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,253}$")


def _sanitize_domain(domain: str) -> str:
    """Validate and sanitize a domain name for use as a filename.

    Returns the sanitized domain.
    Raises ValueError for invalid domains.
    """
    cleaned = domain.strip().lower()

    if not cleaned:
        raise ValueError("Domain cannot be empty")

    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError(f"Domain contains path traversal: {domain!r}")

    if not DOMAIN_PATTERN.match(cleaned):
        raise ValueError(f"Invalid domain format: {domain!r}")

    return cleaned


class SessionCache:
    """Persistent session cookie cache.

    Stores Playwright cookie dicts per domain as JSON files.
    Cookies are stored in the exact format returned by
    ``context.cookies()`` so they can be passed directly to
    ``context.add_cookies()``.

    Usage::

        cache = SessionCache("/workspace/data/sessions")
        await cache.save_session("example.com", cookies)
        cookies = await cache.load_session("example.com")
    """

    def __init__(self, base_dir: str = "/workspace/data/sessions") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _domain_to_path(self, domain: str) -> Path:
        """Map a sanitized domain to its cache file path."""
        sanitized = _sanitize_domain(domain)
        return self._base_dir / f"{sanitized}.json"

    async def save_session(self, domain: str, cookies: list[dict[str, Any]]) -> None:
        """Save browser cookies for a domain.

        Args:
            domain: The domain to cache cookies for.
            cookies: List of Playwright cookie dicts (name, value, domain,
                path, expires, httpOnly, secure, sameSite).
        """
        if not cookies:
            return

        file_path = self._domain_to_path(domain)
        payload = {
            "domain": domain,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "cookie_count": len(cookies),
            "cookies": cookies,
        }

        try:
            file_path.write_text(
                json.dumps(payload, indent=2, default=str),
                encoding="utf-8",
            )
            try:
                os.chmod(str(file_path), 0o600)
            except OSError:
                pass
            logger.info(
                "Session saved for domain=%s cookie_count=%d",
                domain, len(cookies),
            )
        except OSError as e:
            logger.warning("Failed to save session for domain=%s: %s", domain, e)

    async def load_session(self, domain: str) -> list[dict[str, Any]] | None:
        """Load cached cookies for a domain.

        Filters out expired cookies (where expires > 0 and < current time).
        Session cookies (expires == -1 or 0) are kept.

        Returns:
            List of valid cookie dicts, or None if no cache or all expired.
        """
        try:
            file_path = self._domain_to_path(domain)
        except ValueError:
            return None

        if not file_path.exists():
            return None

        try:
            raw = file_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to load session for domain=%s: %s", domain, e)
            return None

        if not isinstance(data, dict):
            return None

        cookies = data.get("cookies")
        if not isinstance(cookies, list):
            return None

        # Filter out expired cookies
        now = time.time()
        valid_cookies = []
        for cookie in cookies:
            if not isinstance(cookie, dict):
                continue
            expires = cookie.get("expires", -1)
            # expires == -1 or 0 → session cookie (valid until browser close)
            # expires > 0 and < now → expired
            if isinstance(expires, (int, float)) and expires > 0 and expires < now:
                continue
            valid_cookies.append(cookie)

        if not valid_cookies:
            # All cookies expired — clean up the file
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

        return valid_cookies

    async def check_expiry(self, domain: str) -> bool:
        """Check if a cached session is still valid.

        Returns:
            True if at least one non-expired cookie exists for the domain.
        """
        cookies = await self.load_session(domain)
        return bool(cookies)

    async def clear_session(self, domain: str) -> None:
        """Delete the cached session for a domain."""
        try:
            file_path = self._domain_to_path(domain)
            file_path.unlink(missing_ok=True)
            logger.info("Session cache cleared for domain=%s", domain)
        except (ValueError, OSError) as e:
            logger.warning("Failed to clear session for domain=%s: %s", domain, e)
