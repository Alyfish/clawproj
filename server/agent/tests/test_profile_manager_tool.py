"""
Tests for ProfileManagerTool.

Covers:
- Tool initialization and properties
- All 4 action handlers (list, create, delete, show_domains)
- Validation (name format, duplicates, defaults)
- Error handling (missing params, unknown actions)
- Integration with real BrowserProfileManager (no mocking)
"""
from __future__ import annotations

import json

import pytest

from server.agent.browser_profiles import BrowserProfileManager
from server.agent.tools.profile_manager import ProfileManagerTool


# ── Init tests ───────────────────────────────────────────────────────


class TestInit:
    def test_name_is_browser_profiles(self):
        tool = ProfileManagerTool(None)
        assert tool.name == "browser_profiles"

    def test_parameters_has_4_actions(self):
        tool = ProfileManagerTool(None)
        actions = tool.parameters["action"]["enum"]
        assert len(actions) == 4
        assert "list" in actions
        assert "create" in actions
        assert "delete" in actions
        assert "show_domains" in actions

    def test_action_is_required(self):
        tool = ProfileManagerTool(None)
        assert tool.parameters["action"]["required"] is True

    def test_name_is_optional(self):
        tool = ProfileManagerTool(None)
        assert tool.parameters["name"]["required"] is False

    def test_notes_is_optional(self):
        tool = ProfileManagerTool(None)
        assert tool.parameters["notes"]["required"] is False


# ── Manager initialization tests ─────────────────────────────────────


class TestProfileManagerInit:
    @pytest.mark.asyncio
    async def test_no_profile_manager_fails(self):
        tool = ProfileManagerTool(None)
        result = await tool.execute(action="list")
        assert not result.success
        assert "not configured" in result.error


# ── List profiles tests ──────────────────────────────────────────────


class TestListProfiles:
    @pytest.mark.asyncio
    async def test_list_profiles_empty(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)
        result = await tool.execute(action="list")

        assert result.success
        profiles = json.loads(result.output)
        assert profiles == []

    @pytest.mark.asyncio
    async def test_list_profiles(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        # Create two profiles
        manager.create_profile("gmail", notes="Gmail account")
        manager.create_profile("work", notes="Work account")

        result = await tool.execute(action="list")

        assert result.success
        profiles = json.loads(result.output)
        assert len(profiles) == 2
        # Check that both profiles are present (order is by last_used desc)
        names = {p["name"] for p in profiles}
        assert names == {"gmail", "work"}
        # Verify structure
        for profile in profiles:
            assert "name" in profile
            assert "created_at" in profile
            assert "last_used" in profile
            assert "authenticated_domains" in profile
            assert "notes" in profile


# ── Create profile tests ─────────────────────────────────────────────


class TestCreateProfile:
    @pytest.mark.asyncio
    async def test_create_profile(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        result = await tool.execute(
            action="create",
            name="gmail",
            notes="Gmail account"
        )

        assert result.success
        profile = json.loads(result.output)
        assert profile["name"] == "gmail"
        assert profile["notes"] == "Gmail account"
        assert profile["created_at"]
        assert profile["last_used"]
        assert profile["authenticated_domains"] == []

        # Verify profile directory was created
        profile_dir = tmp_path / "gmail"
        assert profile_dir.exists()
        assert profile_dir.is_dir()

    @pytest.mark.asyncio
    async def test_create_profile_missing_name(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        result = await tool.execute(action="create")

        assert not result.success
        assert "Missing required parameter: name" in result.error

    @pytest.mark.asyncio
    async def test_create_profile_invalid_name(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        # Test uppercase (invalid)
        result = await tool.execute(action="create", name="UPPER")
        assert not result.success
        assert "Invalid profile name" in result.error

        # Test path traversal attempt
        result = await tool.execute(action="create", name="..")
        assert not result.success
        assert "Invalid profile name" in result.error

        # Test special characters
        result = await tool.execute(action="create", name="test@gmail")
        assert not result.success
        assert "Invalid profile name" in result.error

        # Test starting with hyphen
        result = await tool.execute(action="create", name="-test")
        assert not result.success
        assert "Invalid profile name" in result.error

    @pytest.mark.asyncio
    async def test_create_profile_duplicate(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        # Create first time
        result = await tool.execute(action="create", name="gmail")
        assert result.success

        # Try to create again
        result = await tool.execute(action="create", name="gmail")
        assert not result.success
        assert "already exists" in result.error


# ── Delete profile tests ─────────────────────────────────────────────


class TestDeleteProfile:
    @pytest.mark.asyncio
    async def test_delete_profile(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        # Create a profile
        await tool.execute(action="create", name="temp")

        # Delete it
        result = await tool.execute(action="delete", name="temp")

        assert result.success
        response = json.loads(result.output)
        assert response["deleted"] is True
        assert response["name"] == "temp"

        # Verify it's gone
        profile_dir = tmp_path / "temp"
        assert not profile_dir.exists()

        # Verify metadata is gone
        assert manager.get_profile("temp") is None

    @pytest.mark.asyncio
    async def test_delete_default_fails(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        # Create default profile
        manager.create_profile("default")

        # Try to delete it
        result = await tool.execute(action="delete", name="default")

        assert not result.success
        assert "not found or cannot be deleted" in result.error

        # Verify it still exists
        assert manager.get_profile("default") is not None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        result = await tool.execute(action="delete", name="nonexistent")

        assert not result.success
        assert "not found or cannot be deleted" in result.error

    @pytest.mark.asyncio
    async def test_delete_missing_name(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        result = await tool.execute(action="delete")

        assert not result.success
        assert "Missing required parameter: name" in result.error


# ── Show domains tests ───────────────────────────────────────────────


class TestShowDomains:
    @pytest.mark.asyncio
    async def test_show_domains(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        # Create profile and add domains
        manager.create_profile("gmail")
        manager.add_authenticated_domain("gmail", "google.com")
        manager.add_authenticated_domain("gmail", "gmail.com")

        result = await tool.execute(action="show_domains", name="gmail")

        assert result.success
        response = json.loads(result.output)
        assert response["profile"] == "gmail"
        assert "google.com" in response["authenticated_domains"]
        assert "gmail.com" in response["authenticated_domains"]
        assert len(response["authenticated_domains"]) == 2

    @pytest.mark.asyncio
    async def test_show_domains_empty(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        # Create profile with no domains
        manager.create_profile("work")

        result = await tool.execute(action="show_domains", name="work")

        assert result.success
        response = json.loads(result.output)
        assert response["profile"] == "work"
        assert response["authenticated_domains"] == []

    @pytest.mark.asyncio
    async def test_show_domains_missing_name(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        result = await tool.execute(action="show_domains")

        assert not result.success
        assert "Missing required parameter: name" in result.error

    @pytest.mark.asyncio
    async def test_show_domains_not_found(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        result = await tool.execute(action="show_domains", name="nonexistent")

        assert not result.success
        assert "not found" in result.error


# ── Error handling tests ─────────────────────────────────────────────


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_unknown_action(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        result = await tool.execute(action="fly_to_moon")

        assert not result.success
        assert "Unknown action" in result.error
        assert "fly_to_moon" in result.error
        assert "list, create, delete, show_domains" in result.error

    @pytest.mark.asyncio
    async def test_missing_action(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        result = await tool.execute(action="")

        assert not result.success
        assert "Missing required parameter: action" in result.error

    @pytest.mark.asyncio
    async def test_missing_action_param(self, tmp_path):
        manager = BrowserProfileManager(base_dir=str(tmp_path))
        tool = ProfileManagerTool(manager)

        # Call without action parameter at all
        result = await tool.execute()

        assert not result.success
        assert "Missing required parameter: action" in result.error
