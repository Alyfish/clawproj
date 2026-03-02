"""
Tests for CredentialStore — CRUD, validation, security, tool bridge.

Covers:
  - Name validation (sanitization, path traversal rejection)
  - Credential validation (required fields per type)
  - Set + get roundtrip for all 5 credential types
  - Preserves created_at on overwrite
  - list() returns names only
  - exists() returns True/False
  - delete() removes file
  - Corrupted JSON file handling
  - get_for_tool() maps to correct tool format
  - Env var fallback
  - File permissions (chmod 600)
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from server.agent.credential_store import (
    CredentialStore,
    _validate_credential,
    _validate_name,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def tmp_cred_dir(tmp_path: Path) -> str:
    """Create a temporary directory for credential files."""
    return str(tmp_path / "credentials")


@pytest.fixture
def store(tmp_cred_dir: str) -> CredentialStore:
    """Create a CredentialStore in a temp directory."""
    return CredentialStore(tmp_cred_dir)


# ── Sample data for each type ────────────────────────────────

API_KEY_DATA = {"key": "sk-test-12345", "header": "Authorization", "prefix": "Bearer"}
OAUTH2_DATA = {
    "client_id": "client-abc",
    "client_secret": "secret-xyz",
    "access_token": "at-token-123",
    "refresh_token": "rt-token-456",
    "token_url": "https://auth.example.com/token",
    "expires_at": "2025-12-31T23:59:59+00:00",
}
BEARER_DATA = {"token": "bearer-token-789"}
BASIC_DATA = {"username": "admin", "password": "s3cret"}
CUSTOM_DATA = {
    "headers": {"X-Api-Key": "custom-key-abc"},
    "query_params": {"api_key": "qp-key-def"},
}


# ── Name Validation ──────────────────────────────────────────


class TestNameValidation:
    def test_valid_names(self) -> None:
        assert _validate_name("amadeus") == "amadeus"
        assert _validate_name("serpapi") == "serpapi"
        assert _validate_name("my-api-key") == "my-api-key"
        assert _validate_name("oauth2_google") == "oauth2_google"
        assert _validate_name("a1b2c3") == "a1b2c3"

    def test_normalizes_to_lowercase(self) -> None:
        assert _validate_name("AmAdEuS") == "amadeus"
        assert _validate_name("SerpAPI") == "serpapi"

    def test_strips_whitespace(self) -> None:
        assert _validate_name("  amadeus  ") == "amadeus"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_name("")
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_name("   ")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            _validate_name("a" * 65)

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            _validate_name("../evil")
        with pytest.raises(ValueError, match="path traversal"):
            _validate_name("foo/bar")
        with pytest.raises(ValueError, match="path traversal"):
            _validate_name("foo\\bar")

    def test_rejects_special_chars(self) -> None:
        with pytest.raises(ValueError):
            _validate_name("rm -rf")
        with pytest.raises(ValueError):
            _validate_name("key@host")
        with pytest.raises(ValueError):
            _validate_name("key.name")

    def test_rejects_starting_with_special(self) -> None:
        with pytest.raises(ValueError):
            _validate_name("-starts-with-dash")
        with pytest.raises(ValueError):
            _validate_name("_starts-with-underscore")


# ── Credential Validation ────────────────────────────────────


class TestCredentialValidation:
    def test_rejects_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="Invalid credential type"):
            _validate_credential("password", {"value": "xxx"})

    def test_api_key_requires_key(self) -> None:
        with pytest.raises(ValueError, match="key"):
            _validate_credential("api_key", {})
        # Valid
        _validate_credential("api_key", {"key": "xxx"})

    def test_oauth2_requires_fields(self) -> None:
        with pytest.raises(ValueError):
            _validate_credential("oauth2", {"client_id": "x"})
        # Valid
        _validate_credential("oauth2", OAUTH2_DATA)

    def test_bearer_requires_token(self) -> None:
        with pytest.raises(ValueError, match="token"):
            _validate_credential("bearer", {})
        _validate_credential("bearer", {"token": "xxx"})

    def test_basic_requires_username_password(self) -> None:
        with pytest.raises(ValueError):
            _validate_credential("basic", {"username": "x"})
        _validate_credential("basic", BASIC_DATA)

    def test_custom_requires_headers_or_params(self) -> None:
        with pytest.raises(ValueError, match="headers.*query_params"):
            _validate_credential("custom", {})
        with pytest.raises(ValueError):
            _validate_credential("custom", {"headers": {}})
        _validate_credential("custom", {"headers": {"X-Key": "val"}})
        _validate_credential("custom", {"query_params": {"key": "val"}})


# ── Set + Get Roundtrip ──────────────────────────────────────


class TestSetAndGet:
    def test_api_key_roundtrip(self, store: CredentialStore) -> None:
        store.set("test-api", "api_key", API_KEY_DATA)
        cred = store.get("test-api")
        assert cred is not None
        assert cred["name"] == "test-api"
        assert cred["type"] == "api_key"
        assert cred["data"]["key"] == "sk-test-12345"
        assert "created_at" in cred
        assert "updated_at" in cred

    def test_oauth2_roundtrip(self, store: CredentialStore) -> None:
        store.set("google-oauth", "oauth2", OAUTH2_DATA)
        cred = store.get("google-oauth")
        assert cred is not None
        assert cred["type"] == "oauth2"
        assert cred["data"]["client_id"] == "client-abc"
        assert cred["data"]["access_token"] == "at-token-123"

    def test_bearer_roundtrip(self, store: CredentialStore) -> None:
        store.set("my-bearer", "bearer", BEARER_DATA)
        cred = store.get("my-bearer")
        assert cred is not None
        assert cred["type"] == "bearer"
        assert cred["data"]["token"] == "bearer-token-789"

    def test_basic_roundtrip(self, store: CredentialStore) -> None:
        store.set("db-auth", "basic", BASIC_DATA)
        cred = store.get("db-auth")
        assert cred is not None
        assert cred["type"] == "basic"
        assert cred["data"]["username"] == "admin"

    def test_custom_roundtrip(self, store: CredentialStore) -> None:
        store.set("custom-api", "custom", CUSTOM_DATA)
        cred = store.get("custom-api")
        assert cred is not None
        assert cred["type"] == "custom"
        assert cred["data"]["headers"]["X-Api-Key"] == "custom-key-abc"

    def test_get_nonexistent_returns_none(self, store: CredentialStore) -> None:
        assert store.get("does-not-exist") is None

    def test_get_invalid_name_returns_none(self, store: CredentialStore) -> None:
        assert store.get("../evil") is None


# ── Preserves created_at ─────────────────────────────────────


class TestSetPreservesCreatedAt:
    def test_overwrite_preserves_created_at(self, store: CredentialStore) -> None:
        store.set("my-key", "api_key", {"key": "original"})
        first = store.get("my-key")
        assert first is not None
        original_created = first["created_at"]
        original_updated = first["updated_at"]

        # Overwrite with new data
        store.set("my-key", "api_key", {"key": "updated"})
        second = store.get("my-key")
        assert second is not None

        assert second["created_at"] == original_created
        assert second["updated_at"] >= original_updated
        assert second["data"]["key"] == "updated"


# ── List ─────────────────────────────────────────────────────


class TestList:
    def test_empty_store_returns_empty(self, store: CredentialStore) -> None:
        assert store.list() == []

    def test_returns_names_only(self, store: CredentialStore) -> None:
        store.set("alpha", "api_key", {"key": "a"})
        store.set("bravo", "bearer", {"token": "b"})
        store.set("charlie", "api_key", {"key": "c"})

        names = store.list()
        assert names == ["alpha", "bravo", "charlie"]
        # Ensure no values leaked
        assert all(isinstance(n, str) for n in names)

    def test_list_sorted_alphabetically(self, store: CredentialStore) -> None:
        store.set("zulu", "api_key", {"key": "z"})
        store.set("alpha", "api_key", {"key": "a"})
        assert store.list() == ["alpha", "zulu"]


# ── Exists ───────────────────────────────────────────────────


class TestExists:
    def test_exists_returns_true(self, store: CredentialStore) -> None:
        store.set("my-key", "api_key", {"key": "x"})
        assert store.exists("my-key") is True

    def test_exists_returns_false(self, store: CredentialStore) -> None:
        assert store.exists("no-such-key") is False

    def test_exists_invalid_name_returns_false(self, store: CredentialStore) -> None:
        assert store.exists("../evil") is False


# ── Delete ───────────────────────────────────────────────────


class TestDelete:
    def test_delete_existing(self, store: CredentialStore) -> None:
        store.set("to-delete", "api_key", {"key": "x"})
        assert store.exists("to-delete") is True
        assert store.delete("to-delete") is True
        assert store.exists("to-delete") is False

    def test_delete_nonexistent_returns_false(self, store: CredentialStore) -> None:
        assert store.delete("nope") is False

    def test_delete_invalid_name_returns_false(self, store: CredentialStore) -> None:
        assert store.delete("../evil") is False


# ── Corrupted Files ──────────────────────────────────────────


class TestCorruptedFiles:
    def test_handles_invalid_json(self, store: CredentialStore) -> None:
        # Write garbage to a credential file
        bad_path = Path(store._root) / "broken.json"
        bad_path.write_text("{invalid json!!!", encoding="utf-8")
        assert store.get("broken") is None

    def test_handles_non_dict_json(self, store: CredentialStore) -> None:
        bad_path = Path(store._root) / "array.json"
        bad_path.write_text("[1, 2, 3]", encoding="utf-8")
        assert store.get("array") is None

    def test_list_includes_corrupted_files(self, store: CredentialStore) -> None:
        # list() shows names even for corrupted files (they exist on disk)
        store.set("good", "api_key", {"key": "x"})
        bad_path = Path(store._root) / "bad.json"
        bad_path.write_text("not json", encoding="utf-8")

        names = store.list()
        assert "good" in names
        assert "bad" in names


# ── Get For Tool ─────────────────────────────────────────────


class TestGetForTool:
    def test_api_key_maps_correctly(self, store: CredentialStore) -> None:
        store.set("my-api", "api_key", {"key": "sk-123"})
        result = store.get_for_tool("my-api")
        assert result == {"type": "api_key", "value": "sk-123"}

    def test_bearer_maps_to_api_key(self, store: CredentialStore) -> None:
        store.set("my-bearer", "bearer", {"token": "tok-456"})
        result = store.get_for_tool("my-bearer")
        assert result == {"type": "api_key", "value": "tok-456"}

    def test_basic_maps_to_header(self, store: CredentialStore) -> None:
        store.set("db-auth", "basic", {"username": "admin", "password": "pass"})
        result = store.get_for_tool("db-auth")
        assert result is not None
        assert result["type"] == "header"
        assert result["value"].startswith("Authorization: Basic ")
        # Verify base64 decodes correctly
        import base64

        b64_part = result["value"].split("Basic ")[1]
        decoded = base64.b64decode(b64_part).decode()
        assert decoded == "admin:pass"

    def test_oauth2_maps_to_api_key(self, store: CredentialStore) -> None:
        store.set("google", "oauth2", OAUTH2_DATA)
        result = store.get_for_tool("google")
        assert result == {"type": "api_key", "value": "at-token-123"}

    def test_custom_maps_first_header(self, store: CredentialStore) -> None:
        store.set("custom", "custom", {"headers": {"X-Key": "val123"}})
        result = store.get_for_tool("custom")
        assert result == {"type": "header", "value": "X-Key: val123"}

    def test_nonexistent_returns_none(self, store: CredentialStore) -> None:
        assert store.get_for_tool("nope") is None


# ── Env Var Fallback ─────────────────────────────────────────


class TestEnvVarFallback:
    def test_falls_back_to_env_var(self, store: CredentialStore, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAWBOT_CRED_SERPAPI", "env-key-789")
        result = store.get_for_tool("serpapi")
        assert result == {"type": "api_key", "value": "env-key-789"}

    def test_file_takes_priority_over_env(self, store: CredentialStore, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAWBOT_CRED_MYAPI", "env-value")
        store.set("myapi", "api_key", {"key": "file-value"})
        result = store.get_for_tool("myapi")
        assert result == {"type": "api_key", "value": "file-value"}

    def test_hyphenated_name_env_var(self, store: CredentialStore, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLAWBOT_CRED_MY_API", "env-key")
        result = store.get_for_tool("my-api")
        assert result == {"type": "api_key", "value": "env-key"}

    def test_no_file_no_env_returns_none(self, store: CredentialStore) -> None:
        assert store.get_for_tool("nonexistent") is None


# ── File Permissions ─────────────────────────────────────────


@pytest.mark.skipif(sys.platform == "win32", reason="chmod not reliable on Windows")
class TestFilePermissions:
    def test_file_permissions_600(self, store: CredentialStore) -> None:
        store.set("perm-test", "api_key", {"key": "x"})
        file_path = Path(store._root) / "perm-test.json"
        file_stat = file_path.stat()
        # Check owner read/write only (0o600)
        perms = stat.S_IMODE(file_stat.st_mode)
        assert perms == 0o600

    def test_dir_permissions_700(self, tmp_path: Path) -> None:
        cred_dir = tmp_path / "new-creds"
        CredentialStore(str(cred_dir))
        dir_stat = cred_dir.stat()
        perms = stat.S_IMODE(dir_stat.st_mode)
        assert perms == 0o700
