"""Tests for ClawBot Virtual Filesystem (VFS)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from server.agent.vfs import VFS


@pytest.fixture
def vfs_base(tmp_path: Path) -> str:
    """Temporary workspace base path (not yet created)."""
    return str(tmp_path / "workspace")


@pytest.fixture
def vfs(vfs_base: str) -> VFS:
    """VFS instance backed by a temp directory."""
    return VFS(base=vfs_base)


class TestInit:
    def test_init_creates_all_dirs(self, vfs: VFS, vfs_base: str) -> None:
        vfs.init()
        base = Path(vfs_base)
        for rel_path in VFS.STRUCTURE:
            assert (base / rel_path).is_dir(), f"Missing: {rel_path}"

    def test_init_idempotent(self, vfs: VFS, vfs_base: str) -> None:
        vfs.init()
        marker = Path(vfs_base) / "memory" / "general" / "test-marker.md"
        marker.write_text("marker", encoding="utf-8")

        vfs.init()

        for rel_path in VFS.STRUCTURE:
            assert (Path(vfs_base) / rel_path).is_dir()
        assert marker.exists()
        assert marker.read_text() == "marker"

    def test_readme_created_on_first_init(self, vfs: VFS, vfs_base: str) -> None:
        vfs.init()
        readme = Path(vfs_base) / "README.md"
        assert readme.exists()
        content = readme.read_text(encoding="utf-8")
        assert "ClawBot Workspace" in content
        assert "Directory Structure" in content

    def test_readme_not_overwritten(self, vfs: VFS, vfs_base: str) -> None:
        vfs.init()
        readme = Path(vfs_base) / "README.md"
        readme.write_text("Custom README", encoding="utf-8")

        vfs.init()

        assert readme.read_text(encoding="utf-8") == "Custom README"


class TestDefaultBase:
    def test_default_falls_back_locally(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLAWBOT_WORKSPACE", raising=False)
        vfs = VFS()
        # On macOS /workspace doesn't exist, so should fall back to project root
        assert vfs.base.endswith("/workspace")
        assert not vfs.base.startswith("/workspace")  # not the Docker path


class TestResolve:
    def test_resolve_normal_path(self, vfs: VFS, vfs_base: str) -> None:
        vfs.init()
        resolved = vfs.resolve("memory/general/note.md")
        expected = os.path.realpath(os.path.join(vfs_base, "memory/general/note.md"))
        assert resolved == expected

    def test_resolve_blocks_traversal(self, vfs: VFS) -> None:
        vfs.init()
        with pytest.raises(ValueError, match="Path traversal blocked"):
            vfs.resolve("../../etc/passwd")

    def test_resolve_blocks_symlink_escape(self, vfs: VFS, vfs_base: str) -> None:
        vfs.init()
        escape_link = Path(vfs_base) / "data" / "escape"
        escape_link.symlink_to("/tmp")

        with pytest.raises(ValueError, match="Path traversal blocked"):
            vfs.resolve("data/escape/secrets.txt")


class TestSyncSkills:
    def test_skill_index_file_created(self, vfs: VFS, vfs_base: str, tmp_path: Path) -> None:
        """After sync_skills, INDEX.md exists with expected skills."""
        vfs.init()
        src = tmp_path / "src_skills"
        skill_dir = src / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test.\ntags: [testing]\n---\n# Test Skill\nDo things.\n"
        )
        index_path = vfs.sync_skills(str(src))
        assert Path(index_path).exists()
        content = Path(index_path).read_text()
        assert "test-skill" in content
        assert "testing" in content
        assert "INDEX.md" in index_path

    def test_skill_files_copied(self, vfs: VFS, vfs_base: str, tmp_path: Path) -> None:
        """After sync_skills, SKILL.md files exist in workspace."""
        vfs.init()
        src = tmp_path / "src_skills"
        skill_dir = src / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Mine.\ntags: []\n---\n# My\n"
        )
        vfs.sync_skills(str(src))
        copied = Path(vfs_base) / "skills" / "my-skill" / "SKILL.md"
        assert copied.exists()
        assert "my-skill" in copied.read_text()
