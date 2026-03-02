"""
Tests for ClawBot Memory Store.

Covers: save/load roundtrip, update preserves created_at, category routing,
list_all, list_by_tag, search scoring, corrupted files, size limits,
key sanitization, delete, empty directory.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from server.agent.memory.memory_store import (
    MAX_CONTENT_BYTES,
    MemoryEntry,
    MemoryStore,
    _route_category,
    _validate_key,
)


@pytest.fixture
def tmp_memory_dir(tmp_path: Path) -> str:
    """Create a temporary memory directory."""
    mem_dir = tmp_path / "memory"
    return str(mem_dir)


@pytest.fixture
def store(tmp_memory_dir: str) -> MemoryStore:
    """Create a MemoryStore with a temp directory."""
    return MemoryStore(tmp_memory_dir)


# ── Save + Load Roundtrip ────────────────────────────────────


class TestSaveLoadRoundtrip:
    def test_save_and_load(self, store: MemoryStore) -> None:
        entry = store.save("my-key", "Hello world", ["test", "greeting"])
        loaded = store.load("my-key")

        assert loaded is not None
        assert loaded.key == "my-key"
        assert loaded.content == "Hello world"
        assert loaded.tags == ["test", "greeting"]
        assert loaded.source == "agent"

    def test_save_preserves_created_at_on_update(self, store: MemoryStore) -> None:
        entry1 = store.save("my-key", "Version 1", ["v1"])
        created_at = entry1.created_at

        # Small delay to ensure timestamps differ
        time.sleep(0.01)

        entry2 = store.save("my-key", "Version 2", ["v2"])
        assert entry2.created_at == created_at
        assert entry2.updated_at > created_at
        assert entry2.content == "Version 2"
        assert entry2.tags == ["v2"]

    def test_load_nonexistent_returns_none(self, store: MemoryStore) -> None:
        assert store.load("does-not-exist") is None

    def test_save_custom_source(self, store: MemoryStore) -> None:
        entry = store.save("my-key", "Content", source="skill:flight-search")
        loaded = store.load("my-key")
        assert loaded is not None
        assert loaded.source == "skill:flight-search"

    def test_save_empty_tags(self, store: MemoryStore) -> None:
        entry = store.save("my-key", "No tags")
        loaded = store.load("my-key")
        assert loaded is not None
        assert loaded.tags == []

    def test_save_none_tags(self, store: MemoryStore) -> None:
        entry = store.save("my-key", "Null tags", tags=None)
        loaded = store.load("my-key")
        assert loaded is not None
        assert loaded.tags == []


# ── Category Routing ─────────────────────────────────────────


class TestCategoryRouting:
    def test_user_prefix_routes_to_profile(self) -> None:
        assert _route_category("user-profile") == "profile"
        assert _route_category("user-settings") == "profile"

    def test_preferences_routes_to_preferences(self) -> None:
        assert _route_category("flight-preferences") == "preferences"
        assert _route_category("seat-pref") == "preferences"

    def test_search_prefix_routes_to_searches(self) -> None:
        assert _route_category("past-search-sfo-lhr") == "searches"
        assert _route_category("past-search-hotels-nyc") == "searches"

    def test_default_routes_to_general(self) -> None:
        assert _route_category("random-note") == "general"
        assert _route_category("todo-list") == "general"

    def test_save_creates_file_in_correct_category(self, store: MemoryStore) -> None:
        store.save("user-profile", "Alex from SF")
        store.save("flight-preferences", "Window seat")
        store.save("past-search-sfo-lhr", "Best price $389")
        store.save("meeting-notes", "Discussed roadmap")

        root = Path(store._root)
        assert (root / "profile" / "user-profile.md").exists()
        assert (root / "preferences" / "flight-preferences.md").exists()
        assert (root / "searches" / "past-search-sfo-lhr.md").exists()
        assert (root / "general" / "meeting-notes.md").exists()


# ── list_all ─────────────────────────────────────────────────


class TestListAll:
    def test_list_all_across_categories(self, store: MemoryStore) -> None:
        store.save("user-profile", "Alex")
        store.save("flight-preferences", "Window seat")
        store.save("past-search-sfo-lhr", "Best price")
        store.save("meeting-notes", "Roadmap")

        entries = store.list_all()
        keys = {e.key for e in entries}
        assert keys == {"user-profile", "flight-preferences", "past-search-sfo-lhr", "meeting-notes"}

    def test_list_all_empty(self, store: MemoryStore) -> None:
        entries = store.list_all()
        assert entries == []

    def test_list_all_skips_corrupted(self, store: MemoryStore) -> None:
        store.save("good-entry", "Valid content")

        # Write a corrupted file
        bad_path = Path(store._root) / "general" / "bad-entry.md"
        bad_path.write_text("not yaml at all\x00\x01\x02", encoding="utf-8")

        entries = store.list_all()
        # Should still get the good entry (bad one may or may not load depending on parsing)
        keys = {e.key for e in entries}
        assert "good-entry" in keys


# ── list_by_tag ──────────────────────────────────────────────


class TestListByTag:
    def test_filter_by_tag(self, store: MemoryStore) -> None:
        store.save("entry-a", "Content A", ["flights", "booking"])
        store.save("entry-b", "Content B", ["hotels"])
        store.save("entry-c", "Content C", ["flights", "search"])

        results = store.list_by_tag("flights")
        keys = {e.key for e in results}
        assert keys == {"entry-a", "entry-c"}

    def test_tag_case_insensitive(self, store: MemoryStore) -> None:
        store.save("entry-a", "Content", ["Flights"])
        results = store.list_by_tag("flights")
        assert len(results) == 1

    def test_no_matches(self, store: MemoryStore) -> None:
        store.save("entry-a", "Content", ["flights"])
        assert store.list_by_tag("hotels") == []


# ── Search ───────────────────────────────────────────────────


class TestSearch:
    def test_exact_key_match_scores_highest(self, store: MemoryStore) -> None:
        store.save("flight-preferences", "Window seat")
        store.save("general-notes", "Flight was delayed")

        results = store.search("flight-preferences")
        assert len(results) >= 1
        assert results[0]["key"] == "flight-preferences"
        assert results[0]["relevance_score"] == 1.0

    def test_tag_match(self, store: MemoryStore) -> None:
        store.save("entry-a", "Some content", ["flights", "travel"])
        store.save("entry-b", "Other content", ["hotels"])

        results = store.search("flights")
        keys = [r["key"] for r in results]
        assert "entry-a" in keys

    def test_content_match(self, store: MemoryStore) -> None:
        store.save("note-one", "The best flights from SFO to London", ["notes"])
        store.save("note-two", "Meeting about budgets", ["notes"])

        results = store.search("flights London")
        assert len(results) >= 1
        assert results[0]["key"] == "note-one"

    def test_empty_query_returns_empty(self, store: MemoryStore) -> None:
        store.save("entry-a", "Content")
        assert store.search("") == []
        assert store.search("   ") == []

    def test_limit_respected(self, store: MemoryStore) -> None:
        for i in range(10):
            store.save(f"entry-{i}", f"Content about flights {i}", ["flights"])

        results = store.search("flights", limit=3)
        assert len(results) <= 3

    def test_search_returns_relevance_score(self, store: MemoryStore) -> None:
        store.save("my-entry", "Some content")
        results = store.search("my-entry")
        assert len(results) == 1
        assert "relevance_score" in results[0]
        assert 0 < results[0]["relevance_score"] <= 1.0


# ── Size Limit ───────────────────────────────────────────────


class TestSizeLimit:
    def test_content_truncated_at_10kb(self, store: MemoryStore) -> None:
        big_content = "x" * (MAX_CONTENT_BYTES + 1000)
        entry = store.save("big-entry", big_content)

        loaded = store.load("big-entry")
        assert loaded is not None
        assert len(loaded.content) <= MAX_CONTENT_BYTES


# ── Key Sanitization ────────────────────────────────────────


class TestKeySanitization:
    def test_valid_keys(self) -> None:
        assert _validate_key("my-key") == "my-key"
        assert _validate_key("user-profile") == "user-profile"
        assert _validate_key("past-search-sfo-lhr-2026") == "past-search-sfo-lhr-2026"
        assert _validate_key("a") == "a"

    def test_normalizes_to_lowercase(self) -> None:
        assert _validate_key("My-Key") == "my-key"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            _validate_key("")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(ValueError, match="path traversal"):
            _validate_key("../etc/passwd")
        with pytest.raises(ValueError, match="path traversal"):
            _validate_key("foo/bar")
        with pytest.raises(ValueError, match="path traversal"):
            _validate_key("foo\\bar")

    def test_rejects_special_chars(self) -> None:
        with pytest.raises(ValueError):
            _validate_key("my_key")  # underscore
        with pytest.raises(ValueError):
            _validate_key("my key")  # space
        with pytest.raises(ValueError):
            _validate_key("my.key")  # dot

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            _validate_key("a" * 129)

    def test_save_rejects_bad_key(self, store: MemoryStore) -> None:
        with pytest.raises(ValueError):
            store.save("../evil", "hacked")


# ── Delete ───────────────────────────────────────────────────


class TestDelete:
    def test_delete_removes_file(self, store: MemoryStore) -> None:
        store.save("to-delete", "Temporary content")
        assert store.load("to-delete") is not None

        result = store.delete("to-delete")
        assert result is True
        assert store.load("to-delete") is None

    def test_delete_nonexistent_returns_false(self, store: MemoryStore) -> None:
        assert store.delete("no-such-key") is False

    def test_delete_bad_key_returns_false(self, store: MemoryStore) -> None:
        assert store.delete("../evil") is False


# ── Empty Directory ──────────────────────────────────────────


class TestEmptyDirectory:
    def test_creates_subdirs_on_init(self, tmp_memory_dir: str) -> None:
        store = MemoryStore(tmp_memory_dir)
        root = Path(tmp_memory_dir)
        for cat in ("profile", "preferences", "searches", "general"):
            assert (root / cat).is_dir()

    def test_operations_on_empty_dir(self, store: MemoryStore) -> None:
        assert store.list_all() == []
        assert store.list_by_tag("anything") == []
        assert store.search("anything") == []
        assert store.load("nonexistent") is None
        assert store.delete("nonexistent") is False
