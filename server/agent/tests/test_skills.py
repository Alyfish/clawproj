"""
Tests for ClawBot Skill Loader and Registry.

Creates temporary skill directories with test SKILL.md files
and verifies the full parse → load → registry → tool-call flow.
"""

import os
import tempfile
import threading
from pathlib import Path

import pytest

from server.agent.skill_loader import (
    Skill,
    SkillLoader,
    SkillSummary,
    parse_skill_file,
    _split_frontmatter,
    _ensure_list,
)
from server.agent.skill_registry import (
    SkillRegistry,
    LOAD_SKILL_TOOL,
    execute_load_skill,
)


# ============================================================
# FIXTURES
# ============================================================

VALID_SKILL_MD = """\
---
name: flight-search
description: Search for flights, compare prices, rank results.
tools: [http_request, code_execution, create_card]
approval_actions: [pay, submit]
version: 1.2.0
author: clawbot
tags: [travel, flights]
---
# Context
You are helping the user find flights.

## API Details
Use the Amadeus API to search for flights.
Base URL: https://api.amadeus.com/v2

## Ranking
Rank results by: price (40%), duration (30%), convenience (30%).
"""

MINIMAL_SKILL_MD = """\
---
name: simple-skill
description: A simple skill with no extras.
---
Just do the thing.
"""

NO_FRONTMATTER_MD = """\
# No Frontmatter Skill
This file has no YAML frontmatter at all.
Just raw markdown content.
"""

MALFORMED_YAML_MD = """\
---
name: broken-skill
description: [this is: {invalid yaml
tools: ][
---
Content after bad YAML.
"""

EMPTY_SKILL_MD = """\
---
---
"""


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with test SKILL.md files."""
    # Skill 1: full-featured
    s1 = tmp_path / "flight-search"
    s1.mkdir()
    (s1 / "SKILL.md").write_text(VALID_SKILL_MD)
    (s1 / "api-reference.md").write_text("# Amadeus API\nEndpoints...")
    (s1 / "examples.json").write_text('{"example": true}')
    (s1 / "binary.bin").write_bytes(b"\x00\x01\x02")  # should be skipped

    # Skill 2: minimal
    s2 = tmp_path / "simple-skill"
    s2.mkdir()
    (s2 / "SKILL.md").write_text(MINIMAL_SKILL_MD)

    # Skill 3: malformed YAML
    s3 = tmp_path / "broken-skill"
    s3.mkdir()
    (s3 / "SKILL.md").write_text(MALFORMED_YAML_MD)

    # Skill 4: no frontmatter
    s4 = tmp_path / "no-frontmatter"
    s4.mkdir()
    (s4 / "SKILL.md").write_text(NO_FRONTMATTER_MD)

    # Not a skill directory (no SKILL.md)
    s5 = tmp_path / "random-dir"
    s5.mkdir()
    (s5 / "readme.txt").write_text("not a skill")

    # A file in the root (not a directory, should be skipped)
    (tmp_path / "notes.txt").write_text("some notes")

    return tmp_path


@pytest.fixture
def empty_dir(tmp_path):
    """Empty skills directory."""
    d = tmp_path / "empty-skills"
    d.mkdir()
    return d


# ============================================================
# UNIT TESTS: FRONTMATTER PARSING
# ============================================================

class TestSplitFrontmatter:
    def test_valid_frontmatter(self):
        fm, body = _split_frontmatter("---\nname: test\n---\n# Body")
        assert "name: test" in fm
        assert "# Body" in body

    def test_no_frontmatter(self):
        fm, body = _split_frontmatter("# Just markdown\nNo frontmatter.")
        assert fm == ""
        assert "Just markdown" in body

    def test_empty_frontmatter(self):
        fm, body = _split_frontmatter("---\n---\nBody here")
        assert fm == ""
        assert "Body here" in body

    def test_unclosed_frontmatter(self):
        fm, body = _split_frontmatter("---\nname: test\nNo closing marker")
        assert fm == ""  # falls back to treating as content


class TestEnsureList:
    def test_none(self):
        assert _ensure_list(None) == []

    def test_string(self):
        assert _ensure_list("single") == ["single"]

    def test_list(self):
        assert _ensure_list(["a", "b"]) == ["a", "b"]

    def test_mixed_list(self):
        assert _ensure_list([1, "two", 3]) == ["1", "two", "3"]

    def test_empty_list(self):
        assert _ensure_list([]) == []


# ============================================================
# UNIT TESTS: PARSE SKILL FILE
# ============================================================

class TestParseSkillFile:
    def test_valid_skill(self, skills_dir):
        skill = parse_skill_file(skills_dir / "flight-search" / "SKILL.md")
        assert skill.name == "flight-search"
        assert skill.description == "Search for flights, compare prices, rank results."
        assert skill.tools == ["http_request", "code_execution", "create_card"]
        assert skill.approval_actions == ["pay", "submit"]
        assert skill.version == "1.2.0"
        assert skill.author == "clawbot"
        assert skill.tags == ["travel", "flights"]
        assert "Amadeus API" in skill.content
        assert "Rank results by" in skill.content

    def test_minimal_skill(self, skills_dir):
        skill = parse_skill_file(skills_dir / "simple-skill" / "SKILL.md")
        assert skill.name == "simple-skill"
        assert skill.description == "A simple skill with no extras."
        assert skill.tools == []
        assert skill.approval_actions == []
        assert skill.content == "Just do the thing."

    def test_no_frontmatter(self, skills_dir):
        skill = parse_skill_file(skills_dir / "no-frontmatter" / "SKILL.md")
        # Falls back to directory name
        assert skill.name == "no-frontmatter"
        assert skill.description == ""
        assert "No Frontmatter Skill" in skill.content

    def test_malformed_yaml(self, skills_dir):
        skill = parse_skill_file(skills_dir / "broken-skill" / "SKILL.md")
        # Should not crash — uses fallback to directory name
        assert skill.name == "broken-skill"
        assert "Content after bad YAML" in skill.content

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_skill_file(tmp_path / "nonexistent" / "SKILL.md")

    def test_summary_property(self, skills_dir):
        skill = parse_skill_file(skills_dir / "flight-search" / "SKILL.md")
        assert skill.summary == "- flight-search: Search for flights, compare prices, rank results."


# ============================================================
# UNIT TESTS: SUPPLEMENTARY FILES
# ============================================================

class TestSupplementaryFiles:
    def test_lazy_loading(self, skills_dir):
        skill = parse_skill_file(skills_dir / "flight-search" / "SKILL.md")
        # _supplementary_files should be None before access
        assert skill._supplementary_files is None

        # Access triggers load
        files = skill.supplementary_files
        assert "api-reference.md" in files
        assert "examples.json" in files
        assert "binary.bin" not in files  # wrong extension, skipped
        assert "SKILL.md" not in files  # self, skipped

    def test_no_supplementary(self, skills_dir):
        skill = parse_skill_file(skills_dir / "simple-skill" / "SKILL.md")
        assert skill.supplementary_files == {}


# ============================================================
# INTEGRATION TESTS: SKILL LOADER
# ============================================================

class TestSkillLoader:
    def test_load_all(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        skills = loader.load_all()
        names = {s.name for s in skills}
        # Should load all 4 skills (including malformed — it parses with fallbacks)
        assert "flight-search" in names
        assert "simple-skill" in names
        assert len(skills) >= 2  # at least the well-formed ones

    def test_load_specific(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        skill = loader.load_skill("flight-search")
        assert skill is not None
        assert skill.name == "flight-search"

    def test_load_nonexistent(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        assert loader.load_skill("doesnt-exist") is None

    def test_empty_directory(self, empty_dir):
        loader = SkillLoader(str(empty_dir))
        skills = loader.load_all()
        assert skills == []

    def test_nonexistent_directory(self, tmp_path):
        loader = SkillLoader(str(tmp_path / "nope"))
        skills = loader.load_all()
        assert skills == []

    def test_reload(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        loader.load_all()
        initial_count = len(loader.skills)

        # Add a new skill
        new_skill = skills_dir / "new-skill"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text("---\nname: new-skill\ndescription: Brand new.\n---\nNew content.")

        reloaded = loader.reload()
        assert len(reloaded) == initial_count + 1

    def test_skips_non_directories(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        skills = loader.load_all()
        # notes.txt in root should not cause any skill to load
        names = {s.name for s in skills}
        assert "notes" not in names


# ============================================================
# INTEGRATION TESTS: SKILL REGISTRY
# ============================================================

class TestSkillRegistry:
    def test_initialization(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        assert registry.count >= 2

    def test_get_summaries(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        summaries = registry.get_summaries()
        assert "<available_skills>" in summaries
        assert "</available_skills>" in summaries
        assert "flight-search:" in summaries

    def test_get_skill_content(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        content = registry.get_skill_content("flight-search")
        assert content is not None
        assert '<skill name="flight-search">' in content
        assert "Amadeus API" in content
        assert "</skill>" in content

    def test_get_skill_content_not_found(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        assert registry.get_skill_content("nonexistent") is None

    def test_list_skills(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        listing = registry.list_skills()
        assert all(isinstance(s, SkillSummary) for s in listing)
        names = {s.name for s in listing}
        assert "flight-search" in names

    def test_add_skill(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        initial = registry.count

        dynamic = Skill(
            name="dynamic-skill",
            description="Added at runtime.",
            content="Do the dynamic thing.",
        )
        registry.add_skill(dynamic)
        assert registry.count == initial + 1
        assert registry.get_skill("dynamic-skill") is not None

    def test_remove_skill(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        assert registry.remove_skill("flight-search") is True
        assert registry.get_skill("flight-search") is None
        assert registry.remove_skill("nonexistent") is False

    def test_enable_disable(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)

        registry.disable_skill("flight-search")
        assert "flight-search" not in registry.list_enabled()
        assert "flight-search:" not in registry.get_summaries()

        # Content should be blocked when disabled
        assert registry.get_skill_content("flight-search") is None

        registry.enable_skill("flight-search")
        assert "flight-search" in registry.list_enabled()

    def test_empty_registry(self, empty_dir):
        loader = SkillLoader(str(empty_dir))
        registry = SkillRegistry(loader)
        assert registry.count == 0
        assert "No skills loaded" in registry.get_summaries()

    def test_reload(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        count = registry.reload()
        assert count >= 2


# ============================================================
# INTEGRATION TESTS: LOAD_SKILL TOOL
# ============================================================

class TestLoadSkillTool:
    def test_tool_definition_shape(self):
        assert LOAD_SKILL_TOOL["name"] == "load_skill"
        assert "parameters" in LOAD_SKILL_TOOL
        assert "skill_name" in LOAD_SKILL_TOOL["parameters"]

    def test_execute_success(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        result = execute_load_skill(registry, "flight-search")
        assert result["success"] is True
        assert "Amadeus API" in result["output"]

    def test_execute_not_found(self, skills_dir):
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        result = execute_load_skill(registry, "nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"]
        assert "flight-search" in result["error"]  # lists available


# ============================================================
# THREAD SAFETY
# ============================================================

class TestThreadSafety:
    def test_concurrent_access(self, skills_dir):
        """Verify registry doesn't corrupt under concurrent access."""
        loader = SkillLoader(str(skills_dir))
        registry = SkillRegistry(loader)
        errors = []

        def reader():
            try:
                for _ in range(50):
                    registry.get_summaries()
                    registry.list_skills()
                    registry.get_skill_content("flight-search")
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(50):
                    s = Skill(name=f"dynamic-{i}", description=f"Skill {i}")
                    registry.add_skill(s)
                    registry.remove_skill(f"dynamic-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        threads += [threading.Thread(target=writer) for _ in range(2)]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread safety errors: {errors}"
