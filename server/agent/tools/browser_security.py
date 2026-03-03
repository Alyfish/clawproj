"""
Browser Security Policy — SSRF protection with DNS resolution.

Validates URLs before the agent-controlled browser navigates to them.
Blocks private/internal IPs, dangerous schemes, restricted ports,
and hostnames that resolve to private addresses (DNS rebinding defense).

Pure stdlib — no external dependencies.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Sequence
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UrlCheckResult:
    allowed: bool
    reason: str


class BrowserSecurityPolicy:
    """Centralized URL / network security checks for the browser tool."""

    ALLOWED_SCHEMES = {"http", "https"}
    ALLOWED_PORTS = {80, 443, 8080, 8443}

    BLOCKED_HOSTNAME_EXACT = frozenset({
        "localhost",
        "localhost.localdomain",
        "0.0.0.0",
        "metadata.google.internal",
        "metadata.internal",
        "kubernetes.default.svc",
    })

    BLOCKED_HOSTNAME_PATTERNS = (
        "*.local",
        "*.internal",
        "*.localhost",
    )

    BLOCKED_IP_NETWORKS: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
        # IPv4 private / reserved
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("224.0.0.0/4"),
        ipaddress.ip_network("240.0.0.0/4"),
        ipaddress.ip_network("255.255.255.255/32"),
        # IPv6 private / reserved
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("fc00::/7"),
    ]

    BLOCKED_DOWNLOAD_EXTENSIONS = frozenset({
        ".exe", ".msi", ".dmg", ".sh", ".bat", ".cmd",
        ".app", ".deb", ".rpm", ".pkg", ".apk",
    })

    MAX_JS_SIZE_BYTES = 10_240        # 10 KB
    MAX_RESPONSE_SIZE_BYTES = 1_048_576  # 1 MB
    MAX_NAVIGATIONS_PER_SESSION = 30
    NAVIGATE_TIMEOUT_S = 60

    # ── Synchronous URL check (no DNS) ────────────────────────

    def check_url(self, url: str) -> UrlCheckResult:
        """Validate URL scheme, hostname, port, and raw-IP ranges. No DNS."""
        try:
            parsed = urlparse(url)
        except Exception:
            return UrlCheckResult(False, "Malformed URL")

        # Scheme
        scheme = (parsed.scheme or "").lower()
        if scheme not in self.ALLOWED_SCHEMES:
            return UrlCheckResult(False, f"Blocked scheme: {scheme}")

        # Hostname
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return UrlCheckResult(False, "Missing hostname")

        if hostname in self.BLOCKED_HOSTNAME_EXACT:
            return UrlCheckResult(False, f"Blocked hostname: {hostname}")

        for pattern in self.BLOCKED_HOSTNAME_PATTERNS:
            if fnmatch(hostname, pattern):
                return UrlCheckResult(False, f"Blocked hostname pattern: {hostname}")

        # Port
        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 80
        if port not in self.ALLOWED_PORTS:
            return UrlCheckResult(False, f"Blocked port: {port}")

        # Raw IP check
        try:
            ip = ipaddress.ip_address(hostname)
            if self._is_blocked_ip(ip):
                return UrlCheckResult(False, f"Blocked IP: {hostname}")
        except ValueError:
            pass  # Domain name — checked via DNS in async variant

        return UrlCheckResult(True, "OK")

    # ── Async URL check (with DNS resolution) ─────────────────

    async def check_url_with_dns(self, url: str) -> UrlCheckResult:
        """Full check: synchronous validation + DNS resolution of domain names."""
        sync_result = self.check_url(url)
        if not sync_result.allowed:
            return sync_result

        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        # If hostname is already a raw IP, sync check handled it
        try:
            ipaddress.ip_address(hostname)
            return sync_result  # Already validated
        except ValueError:
            pass  # Domain name — resolve below

        # Resolve DNS and check all returned IPs
        import asyncio
        loop = asyncio.get_running_loop()
        try:
            addrinfo = await loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM),
            )
        except socket.gaierror:
            logger.warning("DNS resolution failed for %s — blocking", hostname)
            return UrlCheckResult(False, f"DNS resolution failed: {hostname}")

        if not addrinfo:
            return UrlCheckResult(False, f"No DNS results for {hostname}")

        for family, _type, _proto, _canonname, sockaddr in addrinfo:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                if self._is_blocked_ip(ip):
                    logger.warning(
                        "SSRF blocked: %s resolved to private IP %s", hostname, ip_str
                    )
                    return UrlCheckResult(
                        False,
                        f"Hostname {hostname} resolves to blocked IP: {ip_str}",
                    )
            except ValueError:
                continue

        return UrlCheckResult(True, "OK")

    # ── Download extension check ──────────────────────────────

    def check_download_url(self, url: str) -> UrlCheckResult:
        """Block URLs pointing to dangerous executable file extensions."""
        try:
            parsed = urlparse(url)
            path = (parsed.path or "").lower()
        except Exception:
            return UrlCheckResult(False, "Malformed URL")

        for ext in self.BLOCKED_DOWNLOAD_EXTENSIONS:
            if path.endswith(ext):
                return UrlCheckResult(False, f"Blocked download extension: {ext}")

        return UrlCheckResult(True, "OK")

    # ── JavaScript size check ─────────────────────────────────

    def check_js_size(self, expression: str) -> UrlCheckResult:
        """Block oversized JavaScript expressions."""
        size = len(expression.encode("utf-8"))
        if size > self.MAX_JS_SIZE_BYTES:
            return UrlCheckResult(
                False,
                f"JS expression too large: {size} bytes (max {self.MAX_JS_SIZE_BYTES})",
            )
        return UrlCheckResult(True, "OK")

    # ── Internal helpers ──────────────────────────────────────

    def _is_blocked_ip(
        self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> bool:
        for network in self.BLOCKED_IP_NETWORKS:
            if ip in network:
                return True
        return False
