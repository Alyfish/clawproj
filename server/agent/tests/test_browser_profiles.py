"""
ClawBot Browser Profile Manager Tests

Comprehensive test suite for BrowserProfileManager and ProfileMetadata.
Uses pytest with tmp_path fixture for isolated filesystem operations.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.agent.browser_profiles import (
    BrowserProfileManager,
    ProfileMetadata,
    METADATA_FILE,
    DEFAULT_PROFILE,
)


class TestProfileMetadata:
    """Test ProfileMetadata dataclass."""

    def test_defaults_set_timestamps(self) -> None:
        """created_at and last_used auto-set when not provided."""
        meta = ProfileMetadata(name="test")

        assert meta.created_at
        assert meta.last_used
        # Timestamps should be ISO format
        datetime.fromisoformat(meta.created_at)
        datetime.fromisoformat(meta.last_used)

    def test_to_dict_roundtrip(self) -> None:
        """to_dict() produces expected keys."""
        meta = ProfileMetadata(
            name="test",
            created_at="2026-01-01T00:00:00+00:00",
            last_used="2026-01-02T00:00:00+00:00",
            authenticated_domains=["example.com", "test.com"],
            notes="Test profile",
        )

        result = meta.to_dict()

        assert result == {
            "name": "test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "last_used": "2026-01-02T00:00:00+00:00",
            "authenticated_domains": ["example.com", "test.com"],
            "notes": "Test profile",
        }

    def test_from_dict_ignores_extra_keys(self) -> None:
        """from_dict with unknown keys works."""
        data = {
            "name": "test",
            "created_at": "2026-01-01T00:00:00+00:00",
            "last_used": "2026-01-02T00:00:00+00:00",
            "authenticated_domains": ["example.com"],
            "notes": "Test",
            "unknown_field": "should be ignored",
            "another_unknown": 123,
        }

        meta = ProfileMetadata.from_dict(data)

        assert meta.name == "test"
        assert meta.created_at == "2026-01-01T00:00:00+00:00"
        assert meta.last_used == "2026-01-02T00:00:00+00:00"
        assert meta.authenticated_domains == ["example.com"]
        assert meta.notes == "Test"
        assert not hasattr(meta, "unknown_field")
        assert not hasattr(meta, "another_unknown")


class TestBrowserProfileManager:
    """Test BrowserProfileManager filesystem operations."""

    def test_init_creates_base_dir(self, tmp_path: Path) -> None:
        """base dir created on init."""
        target_dir = tmp_path / "profiles"
        assert not target_dir.exists()

        BrowserProfileManager(base_dir=str(target_dir))

        assert target_dir.exists()
        assert target_dir.is_dir()

    def test_init_loads_existing_metadata(self, tmp_path: Path) -> None:
        """Create profile, new manager instance loads it."""
        # First instance creates profile
        mgr1 = BrowserProfileManager(base_dir=str(tmp_path))
        mgr1.create_profile("test", notes="First instance")

        # Second instance loads from disk
        mgr2 = BrowserProfileManager(base_dir=str(tmp_path))
        loaded = mgr2.get_profile("test")

        assert loaded is not None
        assert loaded.name == "test"
        assert loaded.notes == "First instance"

    def test_create_profile(self, tmp_path: Path) -> None:
        """Creates profile with correct metadata."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        meta = mgr.create_profile("myprofile", notes="Test notes")

        assert meta.name == "myprofile"
        assert meta.notes == "Test notes"
        assert meta.created_at
        assert meta.last_used
        assert meta.authenticated_domains == []

    def test_create_profile_creates_directory(self, tmp_path: Path) -> None:
        """Profile dir exists on disk."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        mgr.create_profile("myprofile")

        profile_dir = tmp_path / "myprofile"
        assert profile_dir.exists()
        assert profile_dir.is_dir()

    def test_create_profile_duplicate_raises(self, tmp_path: Path) -> None:
        """ValueError on duplicate name."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))
        mgr.create_profile("duplicate")

        with pytest.raises(ValueError, match="already exists"):
            mgr.create_profile("duplicate")

    def test_create_profile_invalid_name_raises(self, tmp_path: Path) -> None:
        """Test invalid profile names."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        invalid_names = [
            "..",
            "../../etc",
            "UPPERCASE",
            "has spaces",
            "",
            "profile/slash",
            "profile\\backslash",
            "profile.dot",
            "profile_underscore",
            "-startswithdash",
            "a" * 64,  # too long
        ]

        for name in invalid_names:
            with pytest.raises(ValueError, match="Invalid profile name"):
                mgr.create_profile(name)

    def test_get_profile(self, tmp_path: Path) -> None:
        """Returns metadata for existing profile."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))
        mgr.create_profile("test", notes="Original notes")

        meta = mgr.get_profile("test")

        assert meta is not None
        assert meta.name == "test"
        assert meta.notes == "Original notes"

    def test_get_profile_not_found(self, tmp_path: Path) -> None:
        """Returns None."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        meta = mgr.get_profile("nonexistent")

        assert meta is None

    def test_get_or_create_default(self, tmp_path: Path) -> None:
        """Creates 'default' profile."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        meta = mgr.get_or_create_default()

        assert meta.name == DEFAULT_PROFILE
        assert "Default" in meta.notes
        profile_dir = tmp_path / DEFAULT_PROFILE
        assert profile_dir.exists()

    def test_get_or_create_default_idempotent(self, tmp_path: Path) -> None:
        """Calling twice returns same profile."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        meta1 = mgr.get_or_create_default()
        meta2 = mgr.get_or_create_default()

        assert meta1.name == meta2.name
        assert meta1.created_at == meta2.created_at

    def test_list_profiles_empty(self, tmp_path: Path) -> None:
        """Returns empty list."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        profiles = mgr.list_profiles()

        assert profiles == []

    def test_list_profiles_sorted_by_last_used(self, tmp_path: Path) -> None:
        """Most recent first."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        # Create three profiles with small delays
        mgr.create_profile("first")
        time.sleep(0.01)
        mgr.create_profile("second")
        time.sleep(0.01)
        mgr.create_profile("third")

        # Update first profile to be most recent
        time.sleep(0.01)
        mgr.update_last_used("first")

        profiles = mgr.list_profiles()
        names = [p.name for p in profiles]

        # first was updated most recently, third created most recently before that
        assert names[0] == "first"
        assert names[1] == "third"
        assert names[2] == "second"

    def test_delete_profile(self, tmp_path: Path) -> None:
        """Removes from metadata."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))
        mgr.create_profile("todelete")

        result = mgr.delete_profile("todelete")

        assert result is True
        assert mgr.get_profile("todelete") is None

    def test_delete_profile_removes_directory(self, tmp_path: Path) -> None:
        """Dir deleted from disk."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))
        mgr.create_profile("todelete")
        profile_dir = tmp_path / "todelete"
        assert profile_dir.exists()

        mgr.delete_profile("todelete")

        assert not profile_dir.exists()

    def test_delete_default_blocked(self, tmp_path: Path) -> None:
        """Returns False for 'default'."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))
        mgr.get_or_create_default()

        result = mgr.delete_profile(DEFAULT_PROFILE)

        assert result is False
        # Profile still exists
        assert mgr.get_profile(DEFAULT_PROFILE) is not None

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        """Returns False."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        result = mgr.delete_profile("nonexistent")

        assert result is False

    def test_update_last_used(self, tmp_path: Path) -> None:
        """Timestamp changes."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))
        meta = mgr.create_profile("test")
        original_timestamp = meta.last_used

        time.sleep(0.01)
        mgr.update_last_used("test")

        updated_meta = mgr.get_profile("test")
        assert updated_meta is not None
        assert updated_meta.last_used != original_timestamp

        # New timestamp should be more recent
        original_dt = datetime.fromisoformat(original_timestamp)
        updated_dt = datetime.fromisoformat(updated_meta.last_used)
        assert updated_dt > original_dt

    def test_add_authenticated_domain(self, tmp_path: Path) -> None:
        """Domain added to list."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))
        mgr.create_profile("test")

        mgr.add_authenticated_domain("test", "example.com")

        meta = mgr.get_profile("test")
        assert meta is not None
        assert "example.com" in meta.authenticated_domains

    def test_add_authenticated_domain_dedup(self, tmp_path: Path) -> None:
        """Adding same domain twice keeps one entry."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))
        mgr.create_profile("test")

        mgr.add_authenticated_domain("test", "example.com")
        mgr.add_authenticated_domain("test", "example.com")

        meta = mgr.get_profile("test")
        assert meta is not None
        assert meta.authenticated_domains.count("example.com") == 1

    def test_get_profile_dir(self, tmp_path: Path) -> None:
        """Returns base_dir / name."""
        mgr = BrowserProfileManager(base_dir=str(tmp_path))

        profile_dir = mgr.get_profile_dir("myprofile")

        assert profile_dir == tmp_path / "myprofile"

    def test_metadata_persists_across_instances(self, tmp_path: Path) -> None:
        """Create manager, add profile, create new manager, verify profile exists."""
        # First manager instance
        mgr1 = BrowserProfileManager(base_dir=str(tmp_path))
        mgr1.create_profile("persistent", notes="Should persist")
        mgr1.add_authenticated_domain("persistent", "example.com")
        mgr1.update_last_used("persistent")

        # Get metadata before destroying manager
        meta1 = mgr1.get_profile("persistent")
        assert meta1 is not None

        # Second manager instance loads from disk
        mgr2 = BrowserProfileManager(base_dir=str(tmp_path))
        meta2 = mgr2.get_profile("persistent")

        assert meta2 is not None
        assert meta2.name == "persistent"
        assert meta2.notes == "Should persist"
        assert "example.com" in meta2.authenticated_domains
        assert meta2.created_at == meta1.created_at
        assert meta2.last_used == meta1.last_used

        # Verify profiles.json exists
        metadata_file = tmp_path / METADATA_FILE
        assert metadata_file.exists()

        # Verify JSON structure
        with open(metadata_file) as f:
            data = json.load(f)

        assert "version" in data
        assert "profiles" in data
        assert "persistent" in data["profiles"]
        assert data["profiles"]["persistent"]["notes"] == "Should persist"
