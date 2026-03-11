"""
ClawBot Credential Store — Auth Application Layer

Persistent credential storage with auth injection for HTTP requests.

Supports credential types:
  - api_key:  Header-based API key injection
  - oauth2:   OAuth2 Bearer tokens with automatic refresh
  - bearer:   Simple Bearer token
  - basic:    HTTP Basic Authentication (base64-encoded)
  - custom:   Arbitrary headers + query params

Storage: JSON files in a credentials directory (one file per credential).
Session 1 will later replace with encrypted persistence.

References:
  - requests-oauthlib (OAuth2 token refresh via POST)
  - httpx-oauth (clean error classes for refresh failures)
  - Google OAuth2 credentials.py (expires_at + 5-min buffer)
  - AgentSecrets CLI for OpenClaw (interactive add/list/delete UX)
  - guillp/requests_oauth2client (BearerToken auto-refresh pattern)

Security:
  - NEVER logs credential values (keys, tokens, passwords)
  - Logs only credential name + type when applying
  - CLI uses getpass for secret inputs
"""
from __future__ import annotations

import base64
import getpass
import json
import logging
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────

CRED_TYPES = ("api_key", "oauth2", "bearer", "basic", "custom", "site_login")
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MAX_NAME_LENGTH = 64

# Refresh OAuth2 tokens 5 minutes before expiry (Google auth pattern)
EXPIRY_BUFFER_SECONDS = 300

# Required fields per credential type
REQUIRED_FIELDS: dict[str, list[str]] = {
    "api_key": ["key"],
    "oauth2": ["client_id", "client_secret", "access_token", "token_url"],
    "bearer": ["token"],
    "basic": ["username", "password"],
    "custom": [],  # validated separately (needs headers OR query_params)
    "site_login": ["url_pattern", "username", "password"],
}


# ── Validation ────────────────────────────────────────────────


def _validate_name(name: str) -> str:
    """Validate and normalize a credential name.

    Rules:
      - Lowercase, alphanumeric + hyphens + underscores
      - No path traversal (/, .., \\)
      - 1-64 characters

    Returns the normalized name.
    Raises ValueError for invalid names.
    """
    normalized = name.strip().lower()

    if not normalized:
        raise ValueError("Credential name cannot be empty")

    if len(normalized) > MAX_NAME_LENGTH:
        raise ValueError(
            f"Credential name too long ({len(normalized)} chars, max {MAX_NAME_LENGTH})"
        )

    if ".." in normalized or "/" in normalized or "\\" in normalized:
        raise ValueError(f"Credential name contains path traversal: {name!r}")

    if not NAME_PATTERN.match(normalized):
        raise ValueError(
            f"Credential name must be lowercase alphanumeric + hyphens/underscores, "
            f"starting with alphanumeric: {name!r}"
        )

    return normalized


def _validate_credential(cred_type: str, data: dict) -> None:
    """Validate credential data for the given type.

    Raises ValueError if required fields are missing or type is invalid.
    """
    if cred_type not in CRED_TYPES:
        raise ValueError(
            f"Invalid credential type: {cred_type!r}. "
            f"Must be one of: {', '.join(CRED_TYPES)}"
        )

    required = REQUIRED_FIELDS[cred_type]
    missing = [f for f in required if f not in data or not data[f]]
    if missing:
        raise ValueError(
            f"Credential type '{cred_type}' requires fields: {', '.join(missing)}"
        )

    # Custom type needs at least one of headers or query_params
    if cred_type == "custom":
        has_headers = "headers" in data and isinstance(data["headers"], dict) and data["headers"]
        has_params = "query_params" in data and isinstance(data["query_params"], dict) and data["query_params"]
        if not has_headers and not has_params:
            raise ValueError(
                "Credential type 'custom' requires at least one of 'headers' or 'query_params'"
            )


# ── Exceptions ──────────────────────────────────────────────


class CredentialNotFoundError(Exception):
    """Raised when a credential is not found in the store."""
    pass


class CredentialRefreshError(Exception):
    """Raised when OAuth2 token refresh fails."""
    pass


# ── Credential Store ────────────────────────────────────────


class CredentialStore:
    """Persistent credential storage with auth injection.

    Storage format: one JSON file per credential in the credentials directory.
    Each file contains: {"type": "api_key", "data": {...}}

    Usage::

        store = CredentialStore(".credentials")
        store.set("amadeus", "api_key", {"key": "xxx", "header": "Authorization"})
        headers, params = store.apply_to_request("amadeus", {}, {})
    """

    def __init__(self, credentials_dir: str = ".credentials/") -> None:
        self._dir = Path(credentials_dir)
        self._root = self._dir  # alias used by tests
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(str(self._dir), 0o700)
        except OSError as e:
            logger.warning("Could not set directory permissions on %s: %s", self._dir, e)
        # Create .gitkeep
        gitkeep = self._dir / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.touch()

    def _path(self, name: str) -> Path:
        """Map a validated credential name to its file path."""
        return self._dir / f"{name}.json"

    # ── CRUD ──────────────────────────────────────────────────

    def set(self, name: str, cred_type: str, data: dict) -> None:
        """Save a credential.

        If the name already exists, preserves created_at and updates updated_at.

        Args:
            name: Unique name (e.g., "amadeus", "serpapi")
            cred_type: One of: api_key, oauth2, bearer, basic, custom
            data: Type-specific credential data

        Raises:
            ValueError: If name is invalid, type is unknown, or required fields missing
        """
        name = _validate_name(name)
        _validate_credential(cred_type, data)

        now = datetime.now(timezone.utc).isoformat()
        file_path = self._path(name)

        # Preserve created_at if updating
        created_at = now
        existing = self._read_file(file_path)
        if existing is not None:
            created_at = existing.get("created_at", now)

        payload = {
            "name": name,
            "type": cred_type,
            "data": data,
            "created_at": created_at,
            "updated_at": now,
        }
        file_path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )

        # Set file permissions to 600 (owner read/write only)
        try:
            os.chmod(str(file_path), 0o600)
        except OSError as e:
            logger.warning("Could not set file permissions on %s: %s", file_path, e)

        logger.info("Saved credential: %s (type: %s)", name, cred_type)

    def get(self, name: str) -> dict | None:
        """Load a credential by name (INTERNAL use only).

        Returns the full credential dict including data, or None if not found.
        NEVER log the returned values.
        """
        try:
            name = _validate_name(name)
        except ValueError:
            return None

        file_path = self._path(name)
        logger.info("Loading credential: %s", name)
        return self._read_file(file_path)

    def delete(self, name: str) -> bool:
        """Delete a credential. Returns True if it existed."""
        try:
            name = _validate_name(name)
        except ValueError:
            return False

        file_path = self._path(name)
        if not file_path.exists():
            return False

        try:
            file_path.unlink()
            logger.info("Deleted credential: name=%s", name)
            return True
        except OSError as e:
            logger.warning("Failed to delete credential %s: %s", name, e)
            return False

    def list(self) -> list[str]:
        """Return credential NAMES only — NEVER return values."""
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def exists(self, name: str) -> bool:
        """Check if a credential exists by name."""
        try:
            name = _validate_name(name)
        except ValueError:
            return False
        return self._path(name).exists()

    # ── GET FOR TOOL ─────────────────────────────────────────

    def get_for_tool(self, name: str) -> dict[str, str] | None:
        """Bridge to the tool credential interface.

        Maps rich credential data to the simple {"type", "value"} format
        that HttpRequestTool and WebSearchTool expect.

        Falls back to CLAWBOT_CRED_{NAME} env var if no file found
        (preserves backward compatibility with the old placeholder).

        Returns:
            {"type": "api_key", "value": "..."} or
            {"type": "header", "value": "HeaderName: value"} or
            None if not found
        """
        cred = self.get(name)

        if cred is not None:
            return self._map_to_tool_format(cred)

        # Env var fallback (backward compat with old get_credential())
        env_key = f"CLAWBOT_CRED_{name.upper().replace('-', '_')}"
        value = os.environ.get(env_key)
        if value:
            return {"type": "api_key", "value": value}

        return None

    # ── Site Login Lookup ───────────────────────────────────

    def get_site_login(self, url: str) -> dict | None:
        """Look up a site_login credential matching the given URL.

        Matches the URL's hostname against stored url_pattern fields.
        A url_pattern matches if the hostname ends with the pattern
        (e.g., "google.com" matches "accounts.google.com").

        Returns:
            {"username": str, "password": str, "name": str} or None.
            NEVER log the returned password.
        """
        try:
            parsed = urlparse(url) if "://" in url else urlparse(f"https://{url}")
            hostname = (parsed.hostname or "").lower()
        except Exception:
            return None

        if not hostname:
            return None

        for cred_name in self.list():
            cred = self.get(cred_name)
            if cred is None or cred.get("type") != "site_login":
                continue
            data = cred.get("data", {})
            pattern = data.get("url_pattern", "").lower().strip()
            if not pattern:
                continue
            # Match: hostname ends with pattern or equals pattern
            if hostname == pattern or hostname.endswith("." + pattern):
                logger.info(
                    "Site login matched: credential=%s domain=%s",
                    cred_name, hostname,
                )
                return {
                    "username": data.get("username", ""),
                    "password": data.get("password", ""),
                    "name": cred_name,
                }

        return None

    # ── Private Helpers ──────────────────────────────────────

    def _read_file(self, file_path: Path) -> dict | None:
        """Read and parse a credential JSON file.

        Returns None if not found or corrupted. Never raises.
        """
        if not file_path.exists():
            return None

        try:
            raw = file_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to read credential file %s: %s", file_path, e)
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("Corrupted credential file %s: %s", file_path, e)
            return None

        if not isinstance(data, dict):
            logger.warning("Invalid credential format in %s: expected dict", file_path)
            return None

        return data

    @staticmethod
    def _map_to_tool_format(cred: dict) -> dict[str, str] | None:
        """Map rich credential data → simple tool format.

        Returns {"type": "api_key"|"header", "value": str} or None.
        """
        cred_type = cred.get("type", "")
        data = cred.get("data", {})

        if cred_type == "api_key":
            key = data.get("key", "")
            if not key:
                return None
            return {"type": "api_key", "value": key}

        if cred_type == "bearer":
            token = data.get("token", "")
            if not token:
                return None
            return {"type": "api_key", "value": token}

        if cred_type == "basic":
            username = data.get("username", "")
            password = data.get("password", "")
            if not username:
                return None
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            return {"type": "header", "value": f"Authorization: Basic {encoded}"}

        if cred_type == "oauth2":
            # TODO: OAuth2 auto-refresh via refresh_token + token_url
            access_token = data.get("access_token", "")
            if not access_token:
                return None
            return {"type": "api_key", "value": access_token}

        if cred_type == "custom":
            headers = data.get("headers", {})
            if headers and isinstance(headers, dict):
                for h_name, h_val in headers.items():
                    return {"type": "header", "value": f"{h_name}: {h_val}"}
            return None

        return None

    # ── Auth Injection ────────────────────────────────────────

    def apply_to_request(
        self,
        name: str,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Inject credential into HTTP request headers/params.

        Args:
            name: Credential name to apply.
            headers: Mutable request headers dict.
            params: Mutable query params dict.

        Returns:
            (headers, params) tuple with credentials injected.

        Raises:
            CredentialNotFoundError: If credential doesn't exist.
            CredentialRefreshError: If OAuth2 refresh fails.
        """
        cred = self.get(name)
        if cred is None:
            raise CredentialNotFoundError(
                f"Credential '{name}' not found. "
                f"Add it with: python -m server.agent.credential_store add"
            )

        cred_type = cred["type"]
        data = cred["data"]

        logger.info("Applying credential '%s' (type: %s) to request", name, cred_type)

        if cred_type == "api_key":
            self._apply_api_key(data, headers)
        elif cred_type == "oauth2":
            self._apply_oauth2(name, data, headers)
        elif cred_type == "bearer":
            self._apply_bearer(data, headers)
        elif cred_type == "basic":
            self._apply_basic(data, headers)
        elif cred_type == "custom":
            self._apply_custom(data, headers, params)
        else:
            raise CredentialNotFoundError(
                f"Unknown credential type '{cred_type}' for '{name}'"
            )

        return headers, params

    # ── Type-specific injectors ───────────────────────────────

    @staticmethod
    def _apply_api_key(data: dict, headers: dict) -> None:
        header_name = data.get("header", "Authorization")
        prefix = data.get("prefix", "Bearer")
        key = data["key"]
        if prefix:
            headers[header_name] = f"{prefix} {key}"
        else:
            headers[header_name] = key

    def _apply_oauth2(self, name: str, data: dict, headers: dict) -> None:
        if _is_token_expired(data):
            self._refresh_oauth2_token(name)
            refreshed = self.get(name)
            if refreshed is not None:
                data = refreshed["data"]
        headers["Authorization"] = f"Bearer {data['access_token']}"

    @staticmethod
    def _apply_bearer(data: dict, headers: dict) -> None:
        headers["Authorization"] = f"Bearer {data['token']}"

    @staticmethod
    def _apply_basic(data: dict, headers: dict) -> None:
        username = data["username"]
        password = data["password"]
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    @staticmethod
    def _apply_custom(data: dict, headers: dict, params: dict) -> None:
        for k, v in data.get("headers", {}).items():
            headers[k] = v
        for k, v in data.get("query_params", {}).items():
            params[k] = v

    # ── OAuth2 Token Refresh ──────────────────────────────────

    def _refresh_oauth2_token(self, name: str) -> None:
        """Refresh an expired OAuth2 token.

        POSTs to the token_url with grant_type=refresh_token.
        Pattern from requests-oauthlib + Google auth library.

        Raises:
            CredentialRefreshError: If refresh fails or no refresh_token.
        """
        cred = self.get(name)
        if cred is None:
            raise CredentialRefreshError(
                f"Cannot refresh: credential '{name}' not found."
            )

        data = cred["data"]

        refresh_token = data.get("refresh_token")
        if not refresh_token:
            raise CredentialRefreshError(
                f"Cannot refresh OAuth2 token for '{name}': "
                f"no refresh_token. User may need to re-authenticate."
            )

        token_url = data.get("token_url")
        if not token_url:
            raise CredentialRefreshError(
                f"Cannot refresh OAuth2 token for '{name}': "
                f"no token_url configured."
            )

        post_data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": data.get("client_id", ""),
            "client_secret": data.get("client_secret", ""),
        }).encode("utf-8")

        req = urllib.request.Request(
            token_url,
            data=post_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        logger.info("Refreshing OAuth2 token for '%s'", name)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    raise CredentialRefreshError(
                        f"Failed to refresh OAuth2 token for '{name}'. "
                        f"Server returned {resp.status}. "
                        f"User may need to re-authenticate."
                    )
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise CredentialRefreshError(
                f"Failed to refresh OAuth2 token for '{name}': {e}. "
                f"User may need to re-authenticate."
            ) from e

        new_access_token = body.get("access_token")
        if not new_access_token:
            raise CredentialRefreshError(
                f"Failed to refresh OAuth2 token for '{name}': "
                f"response missing access_token. "
                f"User may need to re-authenticate."
            )

        expires_in = body.get("expires_in", 3600)
        now = datetime.now(timezone.utc)
        expires_at = now.timestamp() + int(expires_in)

        data["access_token"] = new_access_token
        data["expires_at"] = expires_at

        if "refresh_token" in body:
            data["refresh_token"] = body["refresh_token"]

        self.set(name, "oauth2", data)
        logger.info("OAuth2 token refreshed for '%s'", name)


# ── Token Expiry Check ──────────────────────────────────────


def _is_token_expired(data: dict) -> bool:
    """Check if an OAuth2 token is expired (with 5-minute buffer).

    Google auth pattern: refresh early to avoid request failures.
    If expires_at is missing, assume not expired.
    """
    expires_at = data.get("expires_at")
    if expires_at is None:
        return False

    try:
        expiry_time = float(expires_at)
    except (ValueError, TypeError):
        return False

    now = datetime.now(timezone.utc).timestamp()
    return now >= (expiry_time - EXPIRY_BUFFER_SECONDS)


# ── CLI ─────────────────────────────────────────────────────


def _cli_add(store: CredentialStore) -> None:
    """Interactive credential addition."""
    name = input("Credential name: ").strip()
    if not name:
        print("Error: name cannot be empty")
        return

    cred_type = input("Type (api_key/oauth2/bearer/basic/custom/site_login): ").strip().lower()
    if cred_type not in CRED_TYPES:
        print(f"Error: unknown type '{cred_type}'")
        return

    data: dict[str, Any] = {}

    if cred_type == "api_key":
        data["key"] = getpass.getpass("API Key: ")
        data["header"] = input("Header name (default: Authorization): ").strip() or "Authorization"
        prefix_input = input("Prefix (default: Bearer): ")
        data["prefix"] = prefix_input if prefix_input.strip() != "" else "Bearer"

    elif cred_type == "oauth2":
        data["client_id"] = input("Client ID: ").strip()
        data["client_secret"] = getpass.getpass("Client Secret: ")
        data["token_url"] = input("Token URL: ").strip()
        data["access_token"] = getpass.getpass("Access Token: ")
        refresh = getpass.getpass("Refresh Token (optional, press Enter to skip): ")
        if refresh:
            data["refresh_token"] = refresh

    elif cred_type == "bearer":
        data["token"] = getpass.getpass("Token: ")

    elif cred_type == "basic":
        data["username"] = input("Username: ").strip()
        data["password"] = getpass.getpass("Password: ")

    elif cred_type == "custom":
        headers_raw = input('Custom headers (JSON, e.g. {"X-Api-Key": "xxx"}): ').strip()
        params_raw = input('Custom query params (JSON, e.g. {"api_key": "xxx"}): ').strip()
        try:
            data["headers"] = json.loads(headers_raw) if headers_raw else {}
        except json.JSONDecodeError:
            print("Error: invalid JSON for headers")
            return
        try:
            data["query_params"] = json.loads(params_raw) if params_raw else {}
        except json.JSONDecodeError:
            print("Error: invalid JSON for query params")
            return

    elif cred_type == "site_login":
        data["url_pattern"] = input("URL pattern (e.g., accounts.google.com): ").strip()
        data["username"] = input("Username/email: ").strip()
        data["password"] = getpass.getpass("Password: ")
        data["notes"] = input("Notes (optional): ").strip()

    store.set(name, cred_type, data)
    print(f"Credential '{name}' saved successfully")


def _cli_list(store: CredentialStore) -> None:
    """List credentials (names + types only, never values)."""
    names = store.list()
    if not names:
        print("No credentials stored.")
        return

    for name in names:
        cred = store.get(name)
        cred_type = cred["type"] if cred else "unknown"
        print(f"  - {name} ({cred_type})")


def _cli_delete(store: CredentialStore, name: str) -> None:
    """Delete a credential with confirmation."""
    if not store.exists(name):
        print(f"Credential '{name}' not found")
        return

    confirm = input(f"Delete credential '{name}'? (y/n): ").strip().lower()
    if confirm != "y":
        print("Cancelled")
        return

    if store.delete(name):
        print(f"Credential '{name}' deleted")
    else:
        print(f"Failed to delete credential '{name}'")


def main() -> None:
    """CLI entry point for credential management."""
    default_dir = str(Path.home() / ".clawbot" / "credentials")
    store = CredentialStore(default_dir)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m server.agent.credential_store add")
        print("  python -m server.agent.credential_store list")
        print("  python -m server.agent.credential_store delete <name>")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "add":
        _cli_add(store)
    elif command == "list":
        _cli_list(store)
    elif command == "delete":
        if len(sys.argv) < 3:
            print("Usage: python -m server.agent.credential_store delete <name>")
            sys.exit(1)
        _cli_delete(store, sys.argv[2])
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()


# ── Standalone Fallback ────────────────────────────────────


def get_credential(name: str) -> dict[str, str] | None:
    """Env-var-only credential lookup (backward compat fallback).

    Used when tools are created without a CredentialStore instance.
    Checks CLAWBOT_CRED_{NAME} environment variable.

    Returns:
        {"type": "api_key", "value": "<value>"} or None if not found.
    """
    env_key = f"CLAWBOT_CRED_{name.upper().replace('-', '_')}"
    value = os.environ.get(env_key)
    if value:
        return {"type": "api_key", "value": value}
    return None


# TODO: Add encryption at rest using 'age' (https://github.com/FiloSottile/age)
# TODO: Support OS keychain via 'keyring' library (macOS Keychain, Linux libsecret)
# TODO: Support $KEYCHAIN:secret-name references (like OpenClaw's proposal)
# TODO: Add credential rotation tracking (last_rotated_at, rotation_interval)
