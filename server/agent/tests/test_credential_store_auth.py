"""
Tests for ClawBot Credential Store — Auth Application Layer.

Covers: apply_to_request for all credential types, OAuth2 token refresh,
token expiry checking, CredentialNotFoundError, CLI-friendly error messages,
and full integration workflow.
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.agent.credential_store import (
    EXPIRY_BUFFER_SECONDS,
    CredentialNotFoundError,
    CredentialRefreshError,
    CredentialStore,
    _is_token_expired,
)


@pytest.fixture
def store(tmp_path: Path) -> CredentialStore:
    """Create a CredentialStore with a temp directory."""
    return CredentialStore(str(tmp_path / "credentials"))


# ── API Key ─────────────────────────────────────────────────


class TestApplyApiKey:
    def test_apply_api_key_default_header(self, store: CredentialStore) -> None:
        store.set("amadeus", "api_key", {
            "key": "test-api-key-12345",
            "header": "Authorization",
            "prefix": "Bearer",
        })

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("amadeus", headers, params)

        assert headers["Authorization"] == "Bearer test-api-key-12345"

    def test_apply_api_key_custom_header(self, store: CredentialStore) -> None:
        store.set("serpapi", "api_key", {
            "key": "my-serp-key",
            "header": "X-Api-Key",
            "prefix": "",
        })

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("serpapi", headers, params)

        assert headers["X-Api-Key"] == "my-serp-key"
        assert "Authorization" not in headers

    def test_apply_api_key_defaults(self, store: CredentialStore) -> None:
        """When header and prefix are omitted, defaults to Authorization: Bearer."""
        store.set("simple", "api_key", {"key": "abc123"})

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("simple", headers, params)

        assert headers["Authorization"] == "Bearer abc123"


# ── Bearer ──────────────────────────────────────────────────


class TestApplyBearer:
    def test_apply_bearer(self, store: CredentialStore) -> None:
        store.set("github", "bearer", {"token": "ghp_abc123def456"})

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("github", headers, params)

        assert headers["Authorization"] == "Bearer ghp_abc123def456"


# ── Basic ───────────────────────────────────────────────────


class TestApplyBasic:
    def test_apply_basic(self, store: CredentialStore) -> None:
        store.set("legacy-api", "basic", {
            "username": "admin",
            "password": "secret123",
        })

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("legacy-api", headers, params)

        expected = base64.b64encode(b"admin:secret123").decode()
        assert headers["Authorization"] == f"Basic {expected}"

    def test_apply_basic_special_chars(self, store: CredentialStore) -> None:
        """Password with special characters encodes correctly."""
        store.set("special", "basic", {
            "username": "user@example.com",
            "password": "p@ss:w0rd!",
        })

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("special", headers, params)

        expected = base64.b64encode(b"user@example.com:p@ss:w0rd!").decode()
        assert headers["Authorization"] == f"Basic {expected}"


# ── Custom ──────────────────────────────────────────────────


class TestApplyCustom:
    def test_apply_custom(self, store: CredentialStore) -> None:
        store.set("custom-api", "custom", {
            "headers": {"X-Custom-Auth": "token123", "X-Org": "myorg"},
            "query_params": {"api_key": "qk_abc", "version": "2"},
        })

        headers = {"Content-Type": "application/json"}
        params = {"format": "json"}
        headers, params = store.apply_to_request("custom-api", headers, params)

        assert headers["X-Custom-Auth"] == "token123"
        assert headers["X-Org"] == "myorg"
        assert headers["Content-Type"] == "application/json"  # preserved
        assert params["api_key"] == "qk_abc"
        assert params["version"] == "2"
        assert params["format"] == "json"  # preserved

    def test_apply_custom_minimal(self, store: CredentialStore) -> None:
        """Custom credential with one header doesn't clobber existing headers/params."""
        store.set("minimal", "custom", {
            "headers": {"X-Only": "one"},
            "query_params": {},
        })

        headers = {"Existing": "value"}
        params = {"key": "val"}
        headers, params = store.apply_to_request("minimal", headers, params)

        assert headers["Existing"] == "value"
        assert headers["X-Only"] == "one"
        assert params == {"key": "val"}


# ── OAuth2 ──────────────────────────────────────────────────


class TestApplyOAuth2:
    def test_apply_oauth2_not_expired(self, store: CredentialStore) -> None:
        """Token with future expiry should be applied without refresh."""
        future_ts = datetime.now(timezone.utc).timestamp() + 3600
        store.set("google", "oauth2", {
            "access_token": "ya29.fresh-token",
            "refresh_token": "1//refresh",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id": "client123",
            "client_secret": "secret456",
            "expires_at": future_ts,
        })

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("google", headers, params)

        assert headers["Authorization"] == "Bearer ya29.fresh-token"

    def test_apply_oauth2_no_expiry(self, store: CredentialStore) -> None:
        """Token with no expires_at assumed not expired."""
        store.set("google", "oauth2", {
            "access_token": "ya29.no-expiry",
            "refresh_token": "1//refresh",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id": "client123",
            "client_secret": "secret456",
        })

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("google", headers, params)

        assert headers["Authorization"] == "Bearer ya29.no-expiry"

    @patch("server.agent.credential_store.urllib.request.urlopen")
    def test_apply_oauth2_expired_triggers_refresh(
        self, mock_urlopen: MagicMock, store: CredentialStore
    ) -> None:
        """Expired token should trigger refresh via POST to token_url."""
        past_ts = datetime.now(timezone.utc).timestamp() - 3600
        store.set("google", "oauth2", {
            "access_token": "ya29.old-expired",
            "refresh_token": "1//refresh-token",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id": "client123",
            "client_secret": "secret456",
            "expires_at": past_ts,
        })

        # Mock the refresh response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({
            "access_token": "ya29.new-refreshed",
            "expires_in": 3600,
            "token_type": "Bearer",
        }).encode("utf-8")
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        headers: dict[str, str] = {}
        params: dict[str, str] = {}
        headers, params = store.apply_to_request("google", headers, params)

        assert headers["Authorization"] == "Bearer ya29.new-refreshed"
        mock_urlopen.assert_called_once()

        # Verify the refresh request
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.method == "POST"
        assert "oauth2.googleapis.com" in req.full_url

    def test_apply_oauth2_no_refresh_token(self, store: CredentialStore) -> None:
        """Expired token with no refresh_token raises CredentialRefreshError."""
        past_ts = datetime.now(timezone.utc).timestamp() - 3600
        store.set("google", "oauth2", {
            "access_token": "ya29.old",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id": "client123",
            "client_secret": "secret456",
            "expires_at": past_ts,
        })

        with pytest.raises(CredentialRefreshError, match="no refresh_token"):
            store.apply_to_request("google", {}, {})


# ── Credential Not Found ────────────────────────────────────


class TestCredentialNotFound:
    def test_credential_not_found_error(self, store: CredentialStore) -> None:
        with pytest.raises(CredentialNotFoundError, match="nonexistent"):
            store.apply_to_request("nonexistent", {}, {})

    def test_missing_credential_message_includes_cli_hint(
        self, store: CredentialStore
    ) -> None:
        with pytest.raises(
            CredentialNotFoundError,
            match="python -m server.agent.credential_store add",
        ):
            store.apply_to_request("missing-cred", {}, {})


# ── Token Expiry ────────────────────────────────────────────


class TestIsTokenExpired:
    def test_expired_token(self) -> None:
        past = datetime.now(timezone.utc).timestamp() - 3600
        assert _is_token_expired({"expires_at": past}) is True

    def test_not_expired_token(self) -> None:
        future = datetime.now(timezone.utc).timestamp() + 3600
        assert _is_token_expired({"expires_at": future}) is False

    def test_missing_expires_at(self) -> None:
        assert _is_token_expired({}) is False

    def test_within_buffer_is_expired(self) -> None:
        """Token expiring within 5 minutes should be considered expired."""
        almost_expired = datetime.now(timezone.utc).timestamp() + 60  # 1 min from now
        assert _is_token_expired({"expires_at": almost_expired}) is True

    def test_outside_buffer_not_expired(self) -> None:
        """Token expiring in 10 minutes should NOT be expired (buffer is 5 min)."""
        future = datetime.now(timezone.utc).timestamp() + 600  # 10 min from now
        assert _is_token_expired({"expires_at": future}) is False

    def test_invalid_expires_at(self) -> None:
        assert _is_token_expired({"expires_at": "not-a-number"}) is False

    def test_none_expires_at(self) -> None:
        assert _is_token_expired({"expires_at": None}) is False


# ── CRUD ────────────────────────────────────────────────────


class TestCRUD:
    def test_set_and_get(self, store: CredentialStore) -> None:
        store.set("test", "api_key", {"key": "abc"})
        cred = store.get("test")
        assert cred is not None
        assert cred["type"] == "api_key"
        assert cred["data"]["key"] == "abc"

    def test_get_nonexistent(self, store: CredentialStore) -> None:
        assert store.get("nope") is None

    def test_exists(self, store: CredentialStore) -> None:
        assert store.exists("test") is False
        store.set("test", "bearer", {"token": "x"})
        assert store.exists("test") is True

    def test_delete(self, store: CredentialStore) -> None:
        store.set("test", "bearer", {"token": "x"})
        assert store.delete("test") is True
        assert store.exists("test") is False
        assert store.delete("test") is False

    def test_list(self, store: CredentialStore) -> None:
        store.set("alpha", "bearer", {"token": "a"})
        store.set("beta", "bearer", {"token": "b"})
        names = store.list()
        assert names == ["alpha", "beta"]

    def test_list_empty(self, store: CredentialStore) -> None:
        assert store.list() == []


# ── Integration ─────────────────────────────────────────────


class TestFullWorkflow:
    def test_full_credential_workflow(self, tmp_path: Path) -> None:
        """Full workflow: add credential, apply to request, verify headers."""
        store = CredentialStore(str(tmp_path / ".credentials"))

        # Add API key credential
        store.set("amadeus", "api_key", {
            "key": "test-api-key-12345",
            "header": "Authorization",
            "prefix": "Bearer",
        })

        # Apply to request
        headers = {"Content-Type": "application/json"}
        params = {"format": "json"}
        headers, params = store.apply_to_request("amadeus", headers, params)

        # Verify
        assert headers["Authorization"] == "Bearer test-api-key-12345"
        assert headers["Content-Type"] == "application/json"  # preserved
        assert "format" in params  # preserved

        # Add basic auth credential
        store.set("legacy-api", "basic", {
            "username": "admin",
            "password": "secret123",
        })

        headers2: dict[str, str] = {}
        params2: dict[str, str] = {}
        headers2, params2 = store.apply_to_request("legacy-api", headers2, params2)

        expected = base64.b64encode(b"admin:secret123").decode()
        assert headers2["Authorization"] == f"Basic {expected}"

        # List should show names only
        creds = store.list()
        assert "amadeus" in creds
        assert "legacy-api" in creds

        # Delete
        assert store.delete("amadeus")
        assert not store.exists("amadeus")

        # Missing credential gives helpful error
        with pytest.raises(CredentialNotFoundError, match="python -m"):
            store.apply_to_request("nonexistent", {}, {})

    def test_headers_preserved(self, store: CredentialStore) -> None:
        """Applying credentials should not clobber unrelated headers."""
        store.set("myapi", "bearer", {"token": "xyz"})

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Request-Id": "req-123",
        }
        params = {"page": "1"}

        headers, params = store.apply_to_request("myapi", headers, params)

        assert headers["Authorization"] == "Bearer xyz"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert headers["X-Request-Id"] == "req-123"
        assert params["page"] == "1"
