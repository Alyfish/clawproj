"""
ClawBot Browser Profile Manager

Manages persistent browser profiles for the CDP browser tool.
Each profile is a Chrome user-data-dir that stores cookies,
localStorage, and IndexedDB — login sessions survive restarts.

Storage layout:
    <base_dir>/
        profiles.json          <- metadata index
        default/               <- Chrome user-data-dir
        gmail/                 <- Chrome user-data-dir
        work/                  <- Chrome user-data-dir
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Profile names: lowercase alphanumeric + hyphens, 1-63 chars.
# Prevents path traversal, empty names, and special characters.
PROFILE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]{0,62}$")
DEFAULT_PROFILE = "default"
METADATA_FILE = "profiles.json"


@dataclass
class ProfileMetadata:
    """Metadata for a single browser profile."""

    name: str
    created_at: str = ""
    last_used: str = ""
    authenticated_domains: list[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.last_used:
            self.last_used = now

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProfileMetadata:
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class BrowserProfileManager:
    """Manage persistent browser profiles on disk.

    Each profile maps to a Chrome user-data directory. Metadata
    (timestamps, authenticated domains) is stored in profiles.json.

    Thread-safe: all mutations are guarded by a lock.
    """

    def __init__(self, base_dir: str | None = None) -> None:
        if base_dir is None:
            base_dir = os.environ.get(
                "BROWSER_PROFILES_DIR", "/data/browser-profiles"
            )
        self._base_dir = Path(base_dir)
        self._lock = threading.Lock()
        self._profiles: dict[str, ProfileMetadata] = {}

        # Ensure base directory exists
        self._base_dir.mkdir(parents=True, exist_ok=True)

        # Load existing metadata
        self._load_metadata()

    # ── Public API ─────────────────────────────────────────────

    def create_profile(self, name: str, notes: str = "") -> ProfileMetadata:
        """Create a new browser profile.

        Creates the Chrome user-data directory and metadata entry.

        Raises:
            ValueError: If name is invalid or profile already exists.
        """
        if not PROFILE_NAME_PATTERN.match(name):
            raise ValueError(
                f"Invalid profile name '{name}'. "
                "Must be 1-63 lowercase alphanumeric characters or hyphens, "
                "starting with a letter or digit."
            )

        with self._lock:
            if name in self._profiles:
                raise ValueError(f"Profile '{name}' already exists.")

            # Create Chrome user-data directory
            profile_dir = self._base_dir / name
            profile_dir.mkdir(parents=True, exist_ok=True)

            meta = ProfileMetadata(name=name, notes=notes)
            self._profiles[name] = meta
            self._save_metadata()

            logger.info("Created browser profile: %s at %s", name, profile_dir)
            return meta

    def get_profile(self, name: str) -> ProfileMetadata | None:
        """Get profile metadata by name. Returns None if not found."""
        with self._lock:
            return self._profiles.get(name)

    def get_or_create_default(self) -> ProfileMetadata:
        """Get the default profile, creating it if it doesn't exist."""
        with self._lock:
            if DEFAULT_PROFILE in self._profiles:
                return self._profiles[DEFAULT_PROFILE]

        # Release lock before calling create_profile (which acquires it)
        return self.create_profile(DEFAULT_PROFILE, notes="Default browser profile")

    def list_profiles(self) -> list[ProfileMetadata]:
        """List all profiles, sorted by last_used descending."""
        with self._lock:
            return sorted(
                self._profiles.values(),
                key=lambda p: p.last_used,
                reverse=True,
            )

    def delete_profile(self, name: str) -> bool:
        """Delete a profile and its data directory.

        Cannot delete the default profile. Returns True if deleted.
        """
        if name == DEFAULT_PROFILE:
            logger.warning("Refused to delete default profile")
            return False

        with self._lock:
            if name not in self._profiles:
                return False

            # Remove the Chrome user-data directory
            profile_dir = self._base_dir / name
            if profile_dir.exists():
                shutil.rmtree(profile_dir, ignore_errors=True)

            del self._profiles[name]
            self._save_metadata()

            logger.info("Deleted browser profile: %s", name)
            return True

    def update_last_used(self, name: str) -> None:
        """Update the last_used timestamp for a profile."""
        with self._lock:
            meta = self._profiles.get(name)
            if meta is None:
                return
            meta.last_used = datetime.now(timezone.utc).isoformat()
            self._save_metadata()

    def add_authenticated_domain(self, name: str, domain: str) -> None:
        """Record that a domain has an authenticated session in this profile."""
        with self._lock:
            meta = self._profiles.get(name)
            if meta is None:
                return
            if domain not in meta.authenticated_domains:
                meta.authenticated_domains.append(domain)
                self._save_metadata()
                logger.info(
                    "Added authenticated domain '%s' to profile '%s'",
                    domain, name,
                )

    def get_profile_dir(self, name: str) -> Path:
        """Get the Chrome user-data directory path for a profile."""
        return self._base_dir / name

    # ── Persistence ────────────────────────────────────────────

    def _save_metadata(self) -> None:
        """Write profiles.json atomically. Must hold self._lock."""
        data = {
            "version": 1,
            "profiles": {
                name: meta.to_dict()
                for name, meta in self._profiles.items()
            },
        }
        meta_path = self._base_dir / METADATA_FILE

        # Atomic write: temp file + os.replace
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._base_dir), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, str(meta_path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_metadata(self) -> None:
        """Load profiles.json from disk."""
        meta_path = self._base_dir / METADATA_FILE
        if not meta_path.exists():
            return

        try:
            with open(meta_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load profiles.json: %s", e)
            return

        profiles_raw = data.get("profiles", {})
        for name, raw in profiles_raw.items():
            try:
                self._profiles[name] = ProfileMetadata.from_dict(raw)
            except Exception as e:
                logger.warning("Skipping malformed profile '%s': %s", name, e)
