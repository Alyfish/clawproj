"""
Tests for ClawBot Base Tools.

Tests verify:
- Tool registration and discovery
- Claude API tool_use format output
- Each tool's core functionality
- Error handling and graceful failures
- Security restrictions (file_io, code_execution)
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.agent.tools.tool_registry import BaseTool, ToolRegistry, ToolResult
from server.agent.tools.register import create_registry
from server.agent.tools.http_request import HttpRequestTool
from server.agent.tools.web_search import WebSearchTool
from server.agent.tools.code_execution import CodeExecutionTool
from server.agent.tools.file_io import FileIoTool
from server.agent.tools.create_card import CreateCardTool
from server.agent.tools.memory_tools import SaveMemoryTool, SearchMemoryTool
from server.agent.tools.request_approval import RequestApprovalTool


# ============================================================
# MOCK CLASSES
# ============================================================


class MockGatewayClient:
    """Records emit_event calls; request_approval returns configurable result."""

    def __init__(self, approval_result: Optional[dict] = None) -> None:
        self.events: list[tuple[str, dict]] = []
        self._approval_result = approval_result or {"approved": True, "message": "ok"}

    async def emit_event(self, event: str, payload: dict) -> None:
        self.events.append((event, payload))

    async def request_approval(
        self, action: str, description: str, details: dict
    ) -> dict:
        self.events.append(("approval/requested", {
            "action": action, "description": description, "details": details,
        }))
        return self._approval_result


class MockMemorySystem:
    """Dict-backed save/search for testing."""

    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    async def save(
        self, key: str, content: str, tags: list[str] | None = None
    ) -> None:
        self.store[key] = {"content": content, "tags": tags or []}

    async def search(self, query: str, limit: int = 5) -> list[dict]:
        results = []
        for key, entry in self.store.items():
            if query.lower() in key.lower() or query.lower() in entry["content"].lower():
                results.append({"key": key, **entry})
        return results[:limit]


def mock_credential_store(name: str) -> dict[str, str] | None:
    """Returns API key for known credential names."""
    creds = {
        "serpapi": {"type": "api_key", "value": "test-serpapi-key-123"},
        "openai": {"type": "api_key", "value": "sk-test-openai"},
    }
    return creds.get(name)


# ============================================================
# EXPECTED TOOL NAMES
# ============================================================

EXPECTED_TOOLS = sorted([
    "browser",
    "code_execution",
    "create_card",
    "file_io",
    "http_request",
    "request_approval",
    "save_memory",
    "search_memory",
    "vision",
    "web_search",
])


# ============================================================
# REGISTRY TESTS
# ============================================================


class TestRegistry:
    def test_create_registry_all_tools(self):
        registry = create_registry()
        assert registry.count == 10

    def test_registry_tool_names(self):
        registry = create_registry()
        assert registry.list_tools() == EXPECTED_TOOLS

    def test_registry_definitions_format(self):
        registry = create_registry()
        defs = registry.get_tool_definitions()
        assert len(defs) == 10
        for d in defs:
            assert "name" in d, f"Missing 'name' in {d}"
            assert "description" in d, f"Missing 'description' in {d}"
            assert "parameters" in d, f"Missing 'parameters' in {d}"
            assert isinstance(d["name"], str)
            assert isinstance(d["description"], str)
            assert isinstance(d["parameters"], dict)

    @pytest.mark.asyncio
    async def test_registry_execute_unknown_tool(self):
        registry = create_registry()
        result = await registry.execute("nonexistent_tool", "call-1")
        assert result.success is False
        assert "nonexistent_tool" in result.error
        # Should list available tools
        for name in EXPECTED_TOOLS:
            assert name in result.error

    def test_create_registry_with_dependencies(self):
        gw = MockGatewayClient()
        mem = MockMemorySystem()
        registry = create_registry(
            gateway_client=gw,
            memory_system=mem,
            credential_store=mock_credential_store,
        )
        assert registry.count == 10

    def test_get_definition_format(self):
        """Each tool's get_definition() returns Claude API tool_use format."""
        registry = create_registry()
        for name in EXPECTED_TOOLS:
            tool = registry.get(name)
            defn = tool.get_definition()
            assert defn["name"] == name
            assert "description" in defn
            assert "input_schema" in defn


# ============================================================
# HTTP REQUEST TOOL TESTS
# ============================================================


class TestHttpRequestTool:
    @pytest.mark.asyncio
    async def test_http_get_success(self):
        tool = HttpRequestTool()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"key": "value"}
        mock_response.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.agent.tools.http_request.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(method="GET", url="https://api.example.com/data")

        assert result.success is True
        assert result.output["status_code"] == 200
        assert result.output["body"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_http_post_with_body(self):
        tool = HttpRequestTool()
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 42}
        mock_response.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.agent.tools.http_request.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(
                method="POST",
                url="https://api.example.com/items",
                body={"name": "test"},
            )

        assert result.success is True
        assert result.output["status_code"] == 201
        # Verify body was passed as json kwarg
        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs["json"] == {"name": "test"}

    @pytest.mark.asyncio
    async def test_http_timeout(self):
        import httpx

        tool = HttpRequestTool()

        mock_client = AsyncMock()
        mock_client.request.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.agent.tools.http_request.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(method="GET", url="https://slow.example.com", timeout=5)

        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_http_response_truncation(self):
        tool = HttpRequestTool()
        big_text = "x" * 60_000

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("not json")
        mock_response.text = big_text
        mock_response.headers = {"content-type": "text/plain"}

        mock_client = AsyncMock()
        mock_client.request.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.agent.tools.http_request.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(method="GET", url="https://big.example.com")

        assert result.success is True
        body = result.output["body"]
        assert len(body) < 60_000
        assert "truncated" in body

    @pytest.mark.asyncio
    async def test_http_missing_url(self):
        tool = HttpRequestTool()
        result = await tool.execute(method="GET", url="")
        assert result.success is False
        assert "url" in result.error.lower()


# ============================================================
# WEB SEARCH TOOL TESTS
# ============================================================


class TestWebSearchTool:
    @pytest.mark.asyncio
    async def test_web_search_mock_mode(self, monkeypatch):
        monkeypatch.setenv("CLAWBOT_MOCK_SEARCH", "1")
        tool = WebSearchTool()
        result = await tool.execute(query="flights to London", num_results=3)
        assert result.success is True
        assert len(result.output) == 3
        for item in result.output:
            assert "title" in item
            assert "url" in item
            assert "snippet" in item

    @pytest.mark.asyncio
    async def test_web_search_no_api_key(self, monkeypatch):
        monkeypatch.delenv("CLAWBOT_MOCK_SEARCH", raising=False)
        monkeypatch.delenv("CLAWBOT_CRED_SERPAPI", raising=False)
        tool = WebSearchTool()
        result = await tool.execute(query="test query")
        assert result.success is False
        assert "CLAWBOT_CRED_SERPAPI" in result.error

    @pytest.mark.asyncio
    async def test_web_search_results_format(self, monkeypatch):
        monkeypatch.delenv("CLAWBOT_MOCK_SEARCH", raising=False)
        tool = WebSearchTool(credential_store=mock_credential_store)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "organic_results": [
                {"title": "Result 1", "link": "https://r1.com", "snippet": "Snippet 1"},
                {"title": "Result 2", "link": "https://r2.com", "snippet": "Snippet 2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.agent.tools.web_search.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(query="test", num_results=2)

        assert result.success is True
        assert len(result.output) == 2
        assert result.output[0] == {"title": "Result 1", "url": "https://r1.com", "snippet": "Snippet 1"}
        assert result.output[1] == {"title": "Result 2", "url": "https://r2.com", "snippet": "Snippet 2"}

    @pytest.mark.asyncio
    async def test_web_search_empty_query(self):
        tool = WebSearchTool()
        result = await tool.execute(query="")
        assert result.success is False
        assert "query" in result.error.lower()


# ============================================================
# CODE EXECUTION TOOL TESTS
# ============================================================


class TestCodeExecutionTool:
    @pytest.mark.asyncio
    async def test_python_hello_world(self):
        tool = CodeExecutionTool()
        result = await tool.execute(language="python", code='print("hello")')
        assert result.success is True
        assert result.output["stdout"].strip() == "hello"
        assert result.output["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_python_math(self):
        tool = CodeExecutionTool()
        result = await tool.execute(language="python", code="print(2 + 2)")
        assert result.success is True
        assert result.output["stdout"].strip() == "4"

    @pytest.mark.asyncio
    async def test_python_error(self):
        tool = CodeExecutionTool()
        result = await tool.execute(language="python", code="this is not valid python!!!")
        assert result.success is False
        assert result.output["exit_code"] != 0
        assert "SyntaxError" in result.output["stderr"] or "Error" in result.output["stderr"]

    @pytest.mark.asyncio
    async def test_python_timeout(self):
        tool = CodeExecutionTool()
        result = await tool.execute(
            language="python",
            code="import time; time.sleep(999)",
            timeout=2,
        )
        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_javascript_hello(self):
        if not shutil.which("node"):
            pytest.skip("node not available")
        tool = CodeExecutionTool()
        result = await tool.execute(language="javascript", code='console.log("hi")')
        assert result.success is True
        assert result.output["stdout"].strip() == "hi"

    @pytest.mark.asyncio
    async def test_env_stripped(self):
        tool = CodeExecutionTool()
        result = await tool.execute(
            language="python",
            code='import os; print(os.environ.get("ANTHROPIC_API_KEY", "NOT_FOUND"))',
        )
        assert result.success is True
        assert result.output["stdout"].strip() == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_empty_code(self):
        tool = CodeExecutionTool()
        result = await tool.execute(language="python", code="")
        assert result.success is False
        assert "no code" in result.error.lower()


# ============================================================
# FILE I/O TOOL TESTS
# ============================================================


class TestFileIoTool:
    @pytest.fixture(autouse=True)
    def setup_project_root(self, tmp_path):
        """Create a temp project root with allowed directories."""
        self.root = tmp_path
        (tmp_path / "temp").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "memory").mkdir()
        self.tool = FileIoTool(project_root=str(tmp_path))

    @pytest.mark.asyncio
    async def test_write_and_read(self):
        result = await self.tool.execute(
            action="write", path="temp/test.txt", content="hello world"
        )
        assert result.success is True
        assert result.output["bytes_written"] == 11

        result = await self.tool.execute(action="read", path="temp/test.txt")
        assert result.success is True
        assert result.output["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_write_creates_dirs(self):
        result = await self.tool.execute(
            action="write", path="temp/sub/dir/file.txt", content="nested"
        )
        assert result.success is True
        assert (self.root / "temp" / "sub" / "dir" / "file.txt").exists()

    @pytest.mark.asyncio
    async def test_read_nonexistent(self):
        result = await self.tool.execute(action="read", path="temp/nope.txt")
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_path_server(self):
        result = await self.tool.execute(action="read", path="server/agent/tools.py")
        assert result.success is False
        assert "not an allowed directory" in result.error.lower() or "denied" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocked_path_env(self):
        result = await self.tool.execute(action="read", path=".env")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_blocked_path_soul(self):
        # SOUL.md blocked even within allowed dirs
        (self.root / "temp" / "SOUL.md").write_text("secret")
        result = await self.tool.execute(action="read", path="temp/SOUL.md")
        assert result.success is False
        assert "protected" in result.error.lower() or "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_path_traversal(self):
        result = await self.tool.execute(action="read", path="../../../etc/passwd")
        assert result.success is False
        assert "escapes" in result.error.lower() or "denied" in result.error.lower()

    @pytest.mark.asyncio
    async def test_path_traversal_sneaky(self):
        result = await self.tool.execute(
            action="read", path="skills/../../server/secret.py"
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_list_directory(self):
        (self.root / "temp" / "a.txt").write_text("a")
        (self.root / "temp" / "b.txt").write_text("b")
        result = await self.tool.execute(action="list", path="temp")
        assert result.success is True
        names = [e["name"] for e in result.output["entries"]]
        assert "a.txt" in names
        assert "b.txt" in names

    @pytest.mark.asyncio
    async def test_exists(self):
        (self.root / "temp" / "exists.txt").write_text("hi")
        result = await self.tool.execute(action="exists", path="temp/exists.txt")
        assert result.success is True
        assert result.output["exists"] is True
        assert result.output["is_file"] is True

        result = await self.tool.execute(action="exists", path="temp/nope.txt")
        assert result.success is True
        assert result.output["exists"] is False


# ============================================================
# CREATE CARD TOOL TESTS
# ============================================================


class TestCreateCardTool:
    @pytest.mark.asyncio
    async def test_create_card_basic(self):
        tool = CreateCardTool()
        result = await tool.execute(
            type="flight", title="LAX → JFK", metadata={"price": 299}
        )
        assert result.success is True
        card = result.output
        assert len(card["id"]) == 12  # uuid4 hex[:12]
        assert card["type"] == "flight"
        assert card["title"] == "LAX → JFK"
        assert card["source"] == "agent"
        assert "T" in card["createdAt"]  # ISO 8601

    @pytest.mark.asyncio
    async def test_create_card_emits_event(self):
        gw = MockGatewayClient()
        tool = CreateCardTool(gateway_client=gw)
        result = await tool.execute(
            type="house", title="2BR Apt", metadata={"rent": 1500}
        )
        assert result.success is True
        assert len(gw.events) == 1
        event_name, payload = gw.events[0]
        assert event_name == "card/created"
        assert payload["type"] == "house"

    @pytest.mark.asyncio
    async def test_create_card_no_gateway(self):
        tool = CreateCardTool(gateway_client=None)
        result = await tool.execute(
            type="doc", title="W2 Form", metadata={"pages": 2}
        )
        assert result.success is True
        assert result.output["type"] == "doc"


# ============================================================
# MEMORY TOOLS TESTS
# ============================================================


class TestMemoryTools:
    @pytest.mark.asyncio
    async def test_save_memory_success(self):
        mem = MockMemorySystem()
        tool = SaveMemoryTool(memory_system=mem)
        result = await tool.execute(
            key="user_pref", content="Prefers window seats", tags=["flights"]
        )
        assert result.success is True
        assert result.output["saved"] is True
        assert "user_pref" in mem.store

    @pytest.mark.asyncio
    async def test_search_memory_success(self):
        mem = MockMemorySystem()
        mem.store["user_pref"] = {"content": "Prefers window seats", "tags": ["flights"]}
        tool = SearchMemoryTool(memory_system=mem)
        result = await tool.execute(query="window")
        assert result.success is True
        assert len(result.output) >= 1

    @pytest.mark.asyncio
    async def test_memory_not_configured(self):
        save_tool = SaveMemoryTool(memory_system=None)
        result = await save_tool.execute(key="k", content="v")
        assert result.success is False
        assert "not configured" in result.error.lower()

        search_tool = SearchMemoryTool(memory_system=None)
        result = await search_tool.execute(query="test")
        assert result.success is False
        assert "not configured" in result.error.lower()


# ============================================================
# REQUEST APPROVAL TOOL TESTS
# ============================================================


class TestRequestApprovalTool:
    @pytest.mark.asyncio
    async def test_approval_granted(self):
        gw = MockGatewayClient(approval_result={"approved": True, "message": "ok"})
        tool = RequestApprovalTool(gateway_client=gw)
        result = await tool.execute(
            action="book_flight",
            description="Book LAX→JFK for $299",
            details={"price": 299},
        )
        assert result.success is True
        assert result.output["approved"] is True

    @pytest.mark.asyncio
    async def test_approval_denied(self):
        gw = MockGatewayClient(approval_result={"approved": False, "message": "nope"})
        tool = RequestApprovalTool(gateway_client=gw)
        result = await tool.execute(
            action="send_email",
            description="Send email to boss",
        )
        assert result.success is True
        assert result.output["approved"] is False

    @pytest.mark.asyncio
    async def test_approval_no_gateway(self):
        tool = RequestApprovalTool(gateway_client=None)
        result = await tool.execute(
            action="delete_file",
            description="Delete config.json",
        )
        assert result.success is False
        assert "not configured" in result.error.lower()
