"""Tests for AuthDetector — bash output authentication failure detection."""
from __future__ import annotations

import pytest

from server.agent.tools.auth_detector import AuthDetector


# ── HTTP ──────────────────────────────────────────────────────


class TestHTTPDetection:
    def test_401_in_stderr(self):
        r = AuthDetector.detect("", "HTTP/1.1 401 Unauthorized", 1, "curl https://api.example.com/data")
        assert r is not None
        assert r["tool"] == "http"
        assert r["confidence"] >= 0.9
        assert r["domain"] == "api.example.com"

    def test_403_in_stdout(self):
        r = AuthDetector.detect("HTTP/2 403 Forbidden", "", 1, "curl https://example.com")
        assert r is not None
        assert r["tool"] == "http"

    def test_json_status_401(self):
        body = '{"status": 401, "message": "Not authenticated"}'
        r = AuthDetector.detect(body, "", 1, "curl https://api.stripe.com/v1/charges")
        assert r is not None
        assert r["confidence"] >= 0.85

    def test_json_error_unauthorized(self):
        body = '{"error": "unauthorized", "message": "Invalid token"}'
        r = AuthDetector.detect(body, "", 1, "curl https://api.example.com")
        assert r is not None
        assert r["tool"] == "http"
        assert r["confidence"] >= 0.9

    def test_www_authenticate_header(self):
        r = AuthDetector.detect("", "WWW-Authenticate: Bearer", 1, "curl https://api.example.com")
        assert r is not None
        assert r["tool"] == "http"


# ── GitHub CLI ────────────────────────────────────────────────


class TestGHDetection:
    def test_gh_auth_login(self):
        stderr = "gh: To use GitHub CLI, run: gh auth login"
        r = AuthDetector.detect("", stderr, 1, "gh repo list")
        assert r is not None
        assert r["tool"] == "gh"
        assert r["domain"] == "github.com"
        assert r["confidence"] >= 0.9

    def test_try_authenticating(self):
        stderr = "try authenticating with:  gh auth login"
        r = AuthDetector.detect("", stderr, 1, "gh pr list")
        assert r is not None
        assert r["tool"] == "gh"
        assert r["confidence"] >= 0.95


# ── Git ───────────────────────────────────────────────────────


class TestGitDetection:
    def test_fatal_auth_failed(self):
        stderr = "fatal: Authentication failed for 'https://github.com/user/repo.git'"
        r = AuthDetector.detect("", stderr, 128, "git clone https://github.com/user/repo.git")
        assert r is not None
        assert r["tool"] == "git"
        assert r["confidence"] >= 0.95
        assert r["domain"] == "github.com"

    def test_invalid_username_password(self):
        stderr = "remote: Invalid username or password."
        r = AuthDetector.detect("", stderr, 128, "git push origin main")
        assert r is not None
        assert r["tool"] == "git"

    def test_could_not_read_username(self):
        stderr = "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
        r = AuthDetector.detect("", stderr, 128, "git clone https://github.com/private/repo")
        assert r is not None
        assert r["tool"] == "git"
        assert r["confidence"] >= 0.9


# ── npm ───────────────────────────────────────────────────────


class TestNpmDetection:
    def test_npm_401(self):
        stderr = "npm ERR! 401 Unauthorized - GET https://registry.npmjs.org/@private/pkg"
        r = AuthDetector.detect("", stderr, 1, "npm install @private/pkg")
        assert r is not None
        assert r["tool"] == "npm"
        assert r["confidence"] >= 0.95

    def test_npm_e401_code(self):
        stderr = "npm ERR! code E401"
        r = AuthDetector.detect("", stderr, 1, "npm publish")
        assert r is not None
        assert r["tool"] == "npm"


# ── Docker ────────────────────────────────────────────────────


class TestDockerDetection:
    def test_docker_unauthorized(self):
        stderr = "unauthorized: authentication required"
        r = AuthDetector.detect("", stderr, 1, "docker pull ghcr.io/org/image:latest")
        assert r is not None
        assert r["tool"] == "docker"
        assert r["confidence"] >= 0.9
        assert r["domain"] == "ghcr.io"

    def test_docker_denied(self):
        stderr = "denied: requested access to the resource is denied"
        r = AuthDetector.detect("", stderr, 1, "docker push myregistry.com/img")
        assert r is not None
        assert r["tool"] == "docker"


# ── SSH ───────────────────────────────────────────────────────


class TestSSHDetection:
    def test_publickey_denied(self):
        stderr = "Permission denied (publickey,gssapi-keyex,gssapi-with-mic)."
        r = AuthDetector.detect("", stderr, 255, "ssh user@server.example.com")
        assert r is not None
        assert r["tool"] == "ssh"
        assert r["confidence"] >= 0.9


# ── Edge Cases ────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_detection_on_exit_zero(self):
        r = AuthDetector.detect("HTTP/1.1 401 Unauthorized", "", 0, "curl http://example.com")
        assert r is None

    def test_no_detection_on_non_auth_error(self):
        r = AuthDetector.detect("", "command not found: foo", 127, "foo --bar")
        assert r is None

    def test_no_detection_on_empty_output(self):
        r = AuthDetector.detect("", "", 1, "false")
        assert r is None

    def test_highest_confidence_wins(self):
        # Both generic and specific patterns match
        combined = "Access denied\nnpm ERR! code E401"
        r = AuthDetector.detect(combined, "", 1, "npm install pkg")
        assert r is not None
        assert r["tool"] == "npm"  # npm (0.95) beats generic (0.5)
        assert r["confidence"] >= 0.95

    def test_generic_upgraded_from_command(self):
        r = AuthDetector.detect("", "Access denied", 1, "curl https://api.example.com")
        assert r is not None
        assert r["tool"] == "http"  # generic upgraded to http via command


# ── Domain Extraction ─────────────────────────────────────────


class TestDomainExtraction:
    def test_curl_url(self):
        d = AuthDetector.extract_domain_from_command("curl https://api.example.com/v1/users")
        assert d == "api.example.com"

    def test_git_clone(self):
        d = AuthDetector.extract_domain_from_command("git clone https://github.com/user/repo.git")
        assert d == "github.com"

    def test_gh_always_github(self):
        d = AuthDetector.extract_domain_from_command("gh repo list myorg")
        assert d == "github.com"

    def test_docker_registry(self):
        d = AuthDetector.extract_domain_from_command("docker pull ghcr.io/org/image:latest")
        assert d == "ghcr.io"

    def test_no_domain(self):
        d = AuthDetector.extract_domain_from_command("ls -la")
        assert d is None

    def test_empty_command(self):
        d = AuthDetector.extract_domain_from_command("")
        assert d is None
