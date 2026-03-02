"""
Integration tests for the ClawBot memory system.

Covers: MemoryManager facade (CRUD, search, accessors, context formatting),
MemorySearch typed results, AsyncMemoryAdapter protocol compliance,
and the full save-5-search-various workflow from the spec.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.agent.memory.memory_store import MemoryEntry, MemoryStore
from server.agent.memory.memory_search import MemorySearch, MemorySearchResult
from server.agent.memory.memory_manager import (
    AsyncMemoryAdapter,
    MemoryManager,
    _kebab_to_title,
    _relative_time,
)


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def tmp_memory_dir(tmp_path: Path) -> str:
    """Create a temporary memory directory."""
    return str(tmp_path / "memory")


@pytest.fixture
def store(tmp_memory_dir: str) -> MemoryStore:
    return MemoryStore(tmp_memory_dir)


@pytest.fixture
def search(store: MemoryStore) -> MemorySearch:
    return MemorySearch(store)


@pytest.fixture
def manager(tmp_memory_dir: str) -> MemoryManager:
    return MemoryManager(tmp_memory_dir)


# ── Full Workflow (spec requirement) ─────────────────────────


class TestFullMemoryWorkflow:
    """Integration test: save 5 memories, search with various queries."""

    def test_full_workflow(self, manager: MemoryManager) -> None:
        # Save 5 memories
        manager.save(
            "user-profile",
            "Name: John, Location: San Francisco, Timezone: PST",
            ["personal", "profile"],
        )
        manager.save(
            "flight-preferences",
            "Prefers window seats, United MileagePlus member, flexible on dates",
            ["flights", "preferences"],
        )
        manager.save(
            "past-search-001",
            "Searched SFO→LHR, found $489 on United, Jan 15 departure",
            ["flights", "search", "london"],
        )
        manager.save(
            "past-search-002",
            "Searched SFO→NRT, found $612 on ANA, Feb 20 departure",
            ["flights", "search", "tokyo"],
        )
        manager.save(
            "budget-notes",
            "Max budget $800 for international flights, flexible on domestic",
            ["flights", "budget"],
        )

        # Test 1: Search for flights to London — should find LHR search
        results = manager.search("flight to London")
        assert len(results) > 0
        assert any("LHR" in r.entry.content for r in results)

        # Test 2: Exact key match
        results = manager.search("user-profile")
        assert results[0].entry.key == "user-profile"
        assert results[0].match_type == "exact_key"

        # Test 3: Tag-based discovery
        tagged = manager.store.list_by_tag("flights")
        assert len(tagged) >= 3

        # Test 4: Format for context
        results = manager.search("flight preferences budget")
        context = manager.format_for_context(results)
        assert "## Relevant Memory" in context
        assert len(context) > 0

        # Test 5: Shortcuts work
        profile = manager.get_user_profile()
        assert profile is not None
        assert "John" in profile

        prefs = manager.get_preferences("flight")
        assert prefs is not None
        assert "window" in prefs.lower()

        # Test 6: Search with no results
        results = manager.search("quantum physics")
        # BM25 may return low-scoring partial matches; verify none are strong
        for r in results:
            assert r.score < 0.5

        # Test 7: Delete and verify
        assert manager.store.delete("past-search-002")
        results = manager.search("Tokyo NRT")
        assert not any("NRT" in r.entry.content for r in results)


# ── Empty Manager ────────────────────────────────────────────


class TestEmptyMemoryManager:
    def test_search_empty(self, manager: MemoryManager) -> None:
        results = manager.search("anything")
        assert results == []

    def test_load_missing(self, manager: MemoryManager) -> None:
        assert manager.load("nonexistent") is None

    def test_delete_missing(self, manager: MemoryManager) -> None:
        assert manager.delete("nonexistent") is False

    def test_list_all_empty(self, manager: MemoryManager) -> None:
        assert manager.list_all() == []

    def test_profile_missing(self, manager: MemoryManager) -> None:
        assert manager.get_user_profile() is None

    def test_preferences_missing(self, manager: MemoryManager) -> None:
        assert manager.get_preferences("hotel") is None


# ── MemoryManager CRUD ───────────────────────────────────────


class TestMemoryManagerCrud:
    def test_save_and_load(self, manager: MemoryManager) -> None:
        entry = manager.save("test-key", "Hello world", ["greeting"])
        assert isinstance(entry, MemoryEntry)
        loaded = manager.load("test-key")
        assert loaded is not None
        assert loaded.content == "Hello world"
        assert loaded.tags == ["greeting"]

    def test_save_and_overwrite_preserves_created_at(
        self, manager: MemoryManager
    ) -> None:
        entry1 = manager.save("my-key", "Version 1", ["v1"])
        created_at = entry1.created_at
        entry2 = manager.save("my-key", "Version 2", ["v2"])
        assert entry2.created_at == created_at
        assert entry2.content == "Version 2"
        assert entry2.updated_at >= entry1.updated_at

    def test_delete(self, manager: MemoryManager) -> None:
        manager.save("to-delete", "Temp")
        assert manager.delete("to-delete") is True
        assert manager.load("to-delete") is None

    def test_list_all(self, manager: MemoryManager) -> None:
        manager.save("entry-a", "A")
        manager.save("entry-b", "B")
        entries = manager.list_all()
        keys = {e.key for e in entries}
        assert keys == {"entry-a", "entry-b"}

    def test_list_by_tag(self, manager: MemoryManager) -> None:
        manager.save("tagged-1", "One", ["alpha"])
        manager.save("tagged-2", "Two", ["alpha", "beta"])
        manager.save("tagged-3", "Three", ["beta"])
        alpha = manager.list_by_tag("alpha")
        assert len(alpha) == 2
        assert {e.key for e in alpha} == {"tagged-1", "tagged-2"}


# ── MemorySearch Typed Results ───────────────────────────────


class TestMemorySearch:
    def test_returns_typed_results(self, store: MemoryStore, search: MemorySearch) -> None:
        store.save("flight-preferences", "Window seat, aisle ok")
        results = search.search("flight-preferences")
        assert len(results) >= 1
        assert isinstance(results[0], MemorySearchResult)
        assert isinstance(results[0].entry, MemoryEntry)

    def test_exact_key_match_type(self, store: MemoryStore, search: MemorySearch) -> None:
        store.save("flight-preferences", "Window seat")
        results = search.search("flight-preferences")
        assert results[0].match_type == "exact_key"
        assert results[0].score == 1.0

    def test_empty_query(self, store: MemoryStore, search: MemorySearch) -> None:
        store.save("entry", "Content")
        assert search.search("") == []
        assert search.search("   ") == []

    def test_top_k_limit(self, store: MemoryStore, search: MemorySearch) -> None:
        for i in range(10):
            store.save(f"entry-{i}", f"flights info number {i}", ["flights"])
        results = search.search("flights", top_k=3)
        assert len(results) <= 3

    def test_sorted_by_score(self, store: MemoryStore, search: MemorySearch) -> None:
        store.save("exact-query", "Other content here")
        store.save("note-about-things", "exact-query is mentioned here")
        results = search.search("exact-query")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_as_dicts(self, store: MemoryStore, search: MemorySearch) -> None:
        store.save("my-entry", "Some content", ["tag1"])
        dicts = search.search_as_dicts("my-entry", limit=3)
        assert isinstance(dicts, list)
        assert len(dicts) >= 1
        assert isinstance(dicts[0], dict)
        assert "key" in dicts[0]
        assert "relevance_score" in dicts[0]


# ── MemoryManager Search ─────────────────────────────────────


class TestMemoryManagerSearch:
    def test_search_returns_typed(self, manager: MemoryManager) -> None:
        manager.save("flight-preferences", "Window seat")
        results = manager.search("flight")
        assert isinstance(results, list)
        assert len(results) >= 1
        assert isinstance(results[0], MemorySearchResult)

    def test_search_and_dicts_consistent(self, manager: MemoryManager) -> None:
        manager.save("flight-preferences", "Window seat, United MileagePlus")
        manager.save("user-profile", "Name: Alex, lives in SF")
        typed = manager.search("flight", top_k=3)
        dicts = manager._search.search_as_dicts("flight", limit=3)
        assert len(typed) == len(dicts)
        for t, d in zip(typed, dicts):
            assert d["key"] == t.entry.key


# ── Convenience Accessors ────────────────────────────────────


class TestAccessors:
    def test_get_user_profile(self, manager: MemoryManager) -> None:
        manager.save("user-profile", "Name: Alex, lives in SF", ["user"])
        profile = manager.get_user_profile()
        assert profile is not None
        assert "Alex" in profile

    def test_get_preferences(self, manager: MemoryManager) -> None:
        manager.save(
            "flight-preferences", "Window seat, United MileagePlus", ["flights"]
        )
        prefs = manager.get_preferences("flight")
        assert prefs is not None
        assert "window" in prefs.lower()

    def test_get_preferences_missing_domain(self, manager: MemoryManager) -> None:
        assert manager.get_preferences("hotel") is None


# ── Format for Context ───────────────────────────────────────


class TestFormatForContext:
    def test_empty_results(self, manager: MemoryManager) -> None:
        assert manager.format_for_context([]) == ""

    def test_basic_output(self, manager: MemoryManager) -> None:
        manager.save("flight-preferences", "Window seat, United member", ["flights"])
        results = manager.search("flight", top_k=2)
        output = manager.format_for_context(results)
        assert output.startswith("## Relevant Memory")
        assert "**" in output

    def test_truncation_at_200_chars(self, manager: MemoryManager) -> None:
        long_content = "x" * 300
        entry = manager.save("long-entry", long_content)
        result = MemorySearchResult(entry=entry, score=1.0, match_type="exact_key")
        output = manager.format_for_context([result])
        assert "..." in output
        # Content portion after label should not exceed 200 chars
        content_part = output.split(":** ", 1)[1]
        assert len(content_part) <= 200

    def test_short_content_not_truncated(self, manager: MemoryManager) -> None:
        entry = manager.save("short-entry", "Brief note")
        result = MemorySearchResult(entry=entry, score=1.0, match_type="exact_key")
        output = manager.format_for_context([result])
        assert "..." not in output
        assert "Brief note" in output

    def test_past_search_gets_relative_time(self, manager: MemoryManager) -> None:
        manager.save("past-search-sfo-lhr", "Best price $389")
        results = manager.search("past-search-sfo-lhr")
        output = manager.format_for_context(results)
        assert "(" in output and ")" in output
        assert "ago" in output or "just now" in output

    def test_non_past_search_no_relative_time(self, manager: MemoryManager) -> None:
        manager.save("flight-preferences", "Window seat")
        results = manager.search("flight-preferences")
        output = manager.format_for_context(results)
        assert "ago" not in output
        assert "just now" not in output


# ── Kebab to Title ───────────────────────────────────────────


class TestKebabToTitle:
    def test_simple(self) -> None:
        assert _kebab_to_title("user-profile") == "User Profile"

    def test_multi_word(self) -> None:
        assert _kebab_to_title("flight-preferences") == "Flight Preferences"

    def test_long_key(self) -> None:
        assert _kebab_to_title("past-search-sfo-lhr") == "Past Search Sfo Lhr"

    def test_single_word(self) -> None:
        assert _kebab_to_title("notes") == "Notes"


# ── Relative Time ────────────────────────────────────────────


class TestRelativeTime:
    def test_just_now(self) -> None:
        now = datetime.now(timezone.utc)
        assert _relative_time(now, _now=now) == "just now"

    def test_seconds_ago(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(seconds=30)
        assert _relative_time(dt, _now=now) == "just now"

    def test_singular_minute(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(minutes=1)
        assert _relative_time(dt, _now=now) == "1 minute ago"

    def test_minutes_ago(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(minutes=5)
        assert _relative_time(dt, _now=now) == "5 minutes ago"

    def test_singular_hour(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(hours=1)
        assert _relative_time(dt, _now=now) == "1 hour ago"

    def test_hours_ago(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(hours=3)
        assert _relative_time(dt, _now=now) == "3 hours ago"

    def test_singular_day(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(days=1)
        assert _relative_time(dt, _now=now) == "1 day ago"

    def test_days_ago(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(days=2)
        assert _relative_time(dt, _now=now) == "2 days ago"

    def test_weeks_ago(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(weeks=2)
        assert _relative_time(dt, _now=now) == "2 weeks ago"

    def test_old_date_shows_iso(self) -> None:
        now = datetime.now(timezone.utc)
        dt = now - timedelta(days=60)
        result = _relative_time(dt, _now=now)
        assert result.startswith("on ")
        assert "-" in result


# ── Category Routing Verification ────────────────────────────


class TestCategoryRouting:
    def test_profile_category(self, manager: MemoryManager) -> None:
        entry = manager.save("user-profile", "Name: Alex")
        assert entry.category == "profile"

    def test_preferences_category(self, manager: MemoryManager) -> None:
        entry = manager.save("flight-preferences", "Window seat")
        assert entry.category == "preferences"

    def test_searches_category(self, manager: MemoryManager) -> None:
        entry = manager.save("past-search-sfo-lhr", "Best price $389")
        assert entry.category == "searches"

    def test_general_category(self, manager: MemoryManager) -> None:
        entry = manager.save("budget-notes", "Max $800")
        assert entry.category == "general"

    def test_files_in_correct_subdirs(self, tmp_memory_dir: str) -> None:
        mgr = MemoryManager(tmp_memory_dir)
        mgr.save("user-profile", "Alex")
        mgr.save("flight-preferences", "Window")
        mgr.save("past-search-001", "LHR search")
        mgr.save("budget-notes", "800 max")

        root = Path(tmp_memory_dir)
        assert (root / "profile" / "user-profile.md").exists()
        assert (root / "preferences" / "flight-preferences.md").exists()
        assert (root / "searches" / "past-search-001.md").exists()
        assert (root / "general" / "budget-notes.md").exists()


# ── Async Memory Adapter ────────────────────────────────────


class TestAsyncMemoryAdapter:
    @pytest.mark.asyncio
    async def test_async_save(self, manager: MemoryManager) -> None:
        adapter = AsyncMemoryAdapter(manager)
        await adapter.save("async-key", "Async content", ["test"])
        loaded = manager.load("async-key")
        assert loaded is not None
        assert loaded.content == "Async content"

    @pytest.mark.asyncio
    async def test_async_search(self, manager: MemoryManager) -> None:
        manager.save("flight-preferences", "Window seat, United MileagePlus")
        adapter = AsyncMemoryAdapter(manager)
        results = await adapter.search("flight", limit=3)
        assert isinstance(results, list)
        assert len(results) >= 1
        assert isinstance(results[0], dict)
        assert "key" in results[0]
        assert "relevance_score" in results[0]

    @pytest.mark.asyncio
    async def test_async_search_empty(self, manager: MemoryManager) -> None:
        adapter = AsyncMemoryAdapter(manager)
        results = await adapter.search("nothing here")
        assert results == []
