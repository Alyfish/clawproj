"""
Tests for BrowserSecurityPolicy — SSRF protection with DNS resolution.

All DNS resolution tests use mocked socket.getaddrinfo to avoid
real network access. Tests cover:
- Scheme validation (7 tests)
- Hostname blocking (9 tests)
- IPv4 blocking (12 tests)
- IPv6 blocking (4 tests)
- Port blocking (8 tests)
- DNS resolution (7 tests, async, mocked)
- Download extension blocking (5 tests)
- JavaScript size limits (3 tests)
"""
from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from server.agent.tools.browser_security import BrowserSecurityPolicy, UrlCheckResult


@pytest.fixture
def policy():
    return BrowserSecurityPolicy()


# ── Scheme validation ─────────────────────────────────────────────


class TestSchemeValidation:
    def test_http_allowed(self, policy):
        r = policy.check_url("http://example.com")
        assert r.allowed

    def test_https_allowed(self, policy):
        r = policy.check_url("https://example.com")
        assert r.allowed

    def test_file_blocked(self, policy):
        r = policy.check_url("file:///etc/passwd")
        assert not r.allowed
        assert "scheme" in r.reason.lower()

    def test_ftp_blocked(self, policy):
        r = policy.check_url("ftp://files.example.com")
        assert not r.allowed

    def test_gopher_blocked(self, policy):
        r = policy.check_url("gopher://evil.com")
        assert not r.allowed

    def test_data_blocked(self, policy):
        r = policy.check_url("data:text/html,<h1>hi</h1>")
        assert not r.allowed

    def test_javascript_blocked(self, policy):
        r = policy.check_url("javascript:alert(1)")
        assert not r.allowed


# ── Hostname blocking ────────────────────────────────────────────


class TestHostnameBlocking:
    def test_localhost_blocked(self, policy):
        r = policy.check_url("http://localhost/admin")
        assert not r.allowed
        assert "hostname" in r.reason.lower()

    def test_localhost_localdomain_blocked(self, policy):
        r = policy.check_url("http://localhost.localdomain/admin")
        assert not r.allowed

    def test_zero_ip_hostname_blocked(self, policy):
        r = policy.check_url("http://0.0.0.0/")
        assert not r.allowed

    def test_metadata_google_blocked(self, policy):
        r = policy.check_url("http://metadata.google.internal/computeMetadata/v1/")
        assert not r.allowed

    def test_metadata_internal_blocked(self, policy):
        r = policy.check_url("http://metadata.internal/")
        assert not r.allowed

    def test_kubernetes_svc_blocked(self, policy):
        r = policy.check_url("http://kubernetes.default.svc/api")
        assert not r.allowed

    def test_dot_local_blocked(self, policy):
        r = policy.check_url("http://myprinter.local/")
        assert not r.allowed

    def test_google_com_allowed(self, policy):
        r = policy.check_url("https://google.com")
        assert r.allowed

    def test_kayak_com_allowed(self, policy):
        r = policy.check_url("https://www.kayak.com/flights")
        assert r.allowed


# ── IPv4 blocking ────────────────────────────────────────────────


class TestIPBlocking:
    def test_10_x_blocked(self, policy):
        r = policy.check_url("http://10.0.0.1/")
        assert not r.allowed

    def test_10_255_blocked(self, policy):
        r = policy.check_url("http://10.255.255.255/")
        assert not r.allowed

    def test_172_16_blocked(self, policy):
        r = policy.check_url("http://172.16.0.1/")
        assert not r.allowed

    def test_172_31_blocked(self, policy):
        r = policy.check_url("http://172.31.255.255/")
        assert not r.allowed

    def test_192_168_blocked(self, policy):
        r = policy.check_url("http://192.168.1.1/")
        assert not r.allowed

    def test_127_blocked(self, policy):
        r = policy.check_url("http://127.0.0.1/")
        assert not r.allowed

    def test_127_other_blocked(self, policy):
        r = policy.check_url("http://127.0.0.2/")
        assert not r.allowed

    def test_169_254_blocked(self, policy):
        r = policy.check_url("http://169.254.169.254/latest/meta-data/")
        assert not r.allowed

    def test_100_64_blocked(self, policy):
        r = policy.check_url("http://100.64.0.1/")
        assert not r.allowed

    def test_224_multicast_blocked(self, policy):
        r = policy.check_url("http://224.0.0.1/")
        assert not r.allowed

    def test_240_reserved_blocked(self, policy):
        r = policy.check_url("http://240.0.0.1/")
        assert not r.allowed

    def test_8_8_8_8_allowed(self, policy):
        r = policy.check_url("http://8.8.8.8/")
        assert r.allowed

    def test_1_1_1_1_allowed(self, policy):
        r = policy.check_url("http://1.1.1.1/")
        assert r.allowed


# ── IPv6 blocking ────────────────────────────────────────────────


class TestIPv6Blocking:
    def test_loopback_blocked(self, policy):
        r = policy.check_url("http://[::1]/")
        assert not r.allowed

    def test_link_local_blocked(self, policy):
        r = policy.check_url("http://[fe80::1]/")
        assert not r.allowed

    def test_fc00_blocked(self, policy):
        r = policy.check_url("http://[fc00::1]/")
        assert not r.allowed

    def test_fd00_blocked(self, policy):
        r = policy.check_url("http://[fd00::1]/")
        assert not r.allowed


# ── Port blocking ────────────────────────────────────────────────


class TestPortBlocking:
    def test_80_allowed(self, policy):
        r = policy.check_url("http://example.com:80/")
        assert r.allowed

    def test_443_allowed(self, policy):
        r = policy.check_url("https://example.com:443/")
        assert r.allowed

    def test_8080_allowed(self, policy):
        r = policy.check_url("http://example.com:8080/")
        assert r.allowed

    def test_8443_allowed(self, policy):
        r = policy.check_url("https://example.com:8443/")
        assert r.allowed

    def test_22_ssh_blocked(self, policy):
        r = policy.check_url("http://example.com:22/")
        assert not r.allowed
        assert "port" in r.reason.lower()

    def test_3306_mysql_blocked(self, policy):
        r = policy.check_url("http://example.com:3306/")
        assert not r.allowed

    def test_6379_redis_blocked(self, policy):
        r = policy.check_url("http://example.com:6379/")
        assert not r.allowed

    def test_default_port_inferred(self, policy):
        # No explicit port — should infer 80 for http, which is allowed
        r = policy.check_url("http://example.com/path")
        assert r.allowed
        # And 443 for https
        r2 = policy.check_url("https://example.com/path")
        assert r2.allowed


# ── DNS resolution (async, mocked) ──────────────────────────────


def _make_addrinfo(ip: str, family=socket.AF_INET):
    """Helper to create a getaddrinfo result tuple."""
    return (family, socket.SOCK_STREAM, 0, "", (ip, 0))


class TestDNSResolution:
    @pytest.mark.asyncio
    async def test_domain_resolving_to_private_ip_blocked(self, policy):
        with patch("socket.getaddrinfo", return_value=[_make_addrinfo("10.0.0.1")]):
            r = await policy.check_url_with_dns("https://evil.com/steal")
        assert not r.allowed
        assert "10.0.0.1" in r.reason

    @pytest.mark.asyncio
    async def test_domain_resolving_to_public_ip_allowed(self, policy):
        with patch("socket.getaddrinfo", return_value=[_make_addrinfo("93.184.216.34")]):
            r = await policy.check_url_with_dns("https://example.com/")
        assert r.allowed

    @pytest.mark.asyncio
    async def test_dns_failure_blocks(self, policy):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("NXDOMAIN")):
            r = await policy.check_url_with_dns("https://nonexistent.example.com/")
        assert not r.allowed
        assert "DNS resolution failed" in r.reason

    @pytest.mark.asyncio
    async def test_raw_ip_skips_dns(self, policy):
        """Raw IPs are validated synchronously — no DNS lookup needed."""
        with patch("socket.getaddrinfo") as mock_dns:
            r = await policy.check_url_with_dns("http://8.8.8.8/")
        assert r.allowed
        mock_dns.assert_not_called()

    @pytest.mark.asyncio
    async def test_raw_private_ip_blocked_without_dns(self, policy):
        with patch("socket.getaddrinfo") as mock_dns:
            r = await policy.check_url_with_dns("http://192.168.1.1/")
        assert not r.allowed
        mock_dns.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_ips_one_bad_blocks(self, policy):
        """If any resolved IP is private, the entire URL is blocked."""
        with patch(
            "socket.getaddrinfo",
            return_value=[
                _make_addrinfo("93.184.216.34"),  # public
                _make_addrinfo("10.0.0.1"),       # private
            ],
        ):
            r = await policy.check_url_with_dns("https://dual-stack.example.com/")
        assert not r.allowed
        assert "10.0.0.1" in r.reason

    @pytest.mark.asyncio
    async def test_cloud_metadata_via_dns_blocked(self, policy):
        """Hostname resolving to link-local metadata IP is blocked."""
        with patch(
            "socket.getaddrinfo",
            return_value=[_make_addrinfo("169.254.169.254")],
        ):
            r = await policy.check_url_with_dns("https://metadata-alias.example.com/")
        assert not r.allowed
        assert "169.254.169.254" in r.reason


# ── Download extension blocking ──────────────────────────────────


class TestDownloadBlocking:
    def test_exe_blocked(self, policy):
        r = policy.check_download_url("https://example.com/malware.exe")
        assert not r.allowed
        assert ".exe" in r.reason

    def test_dmg_blocked(self, policy):
        r = policy.check_download_url("https://example.com/app.dmg")
        assert not r.allowed

    def test_sh_blocked(self, policy):
        r = policy.check_download_url("https://example.com/install.sh")
        assert not r.allowed

    def test_html_allowed(self, policy):
        r = policy.check_download_url("https://example.com/page.html")
        assert r.allowed

    def test_pdf_allowed(self, policy):
        r = policy.check_download_url("https://example.com/report.pdf")
        assert r.allowed


# ── JavaScript size limits ───────────────────────────────────────


class TestJSSize:
    def test_small_expression_allowed(self, policy):
        r = policy.check_js_size("document.title")
        assert r.allowed

    def test_large_expression_blocked(self, policy):
        r = policy.check_js_size("x" * 20_000)
        assert not r.allowed
        assert "too large" in r.reason.lower()

    def test_at_limit_allowed(self, policy):
        expr = "x" * policy.MAX_JS_SIZE_BYTES
        r = policy.check_js_size(expr)
        assert r.allowed
