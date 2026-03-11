"""
Integration tests for ClawBot v2 — bash_execute + SearXNG pipeline.

All tests are marked @pytest.mark.integration so normal `pytest` skips
them.  Run with: pytest -m integration -v

Tests requiring Docker (SearXNG, /workspace) will fail gracefully
when run outside the container stack.  Security and timeout tests
work anywhere.
"""
from __future__ import annotations

import pytest

from server.agent.tools.bash_execute import BashExecuteTool
from server.agent.tools.web_search import WebSearchTool


pytestmark = pytest.mark.integration


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def bash():
    return BashExecuteTool()


@pytest.fixture
def search():
    def no_serpapi(name):
        return None
    return WebSearchTool(credential_store=no_serpapi)


# ============================================================
# INFRASTRUCTURE TESTS
# ============================================================


@pytest.mark.asyncio
async def test_searxng_healthy(bash):
    """SearXNG container responds to healthcheck."""
    result = await bash.execute(
        command="curl -sf http://searxng:8080/healthz",
        working_dir="/workspace",
    )
    assert result.success, f"SearXNG healthcheck failed: {result.error}"
    assert result.output["exit_code"] == 0


@pytest.mark.asyncio
async def test_workspace_exists(bash):
    """Workspace directories exist in the container."""
    result = await bash.execute(
        command=(
            "test -d /workspace && "
            "test -d /workspace/memory && "
            "test -d /workspace/scripts && "
            "test -d /workspace/data && "
            "echo OK"
        ),
        working_dir="/workspace",
    )
    assert result.success, f"Workspace dirs missing: {result.error}"
    assert "OK" in result.output["stdout"]


@pytest.mark.asyncio
async def test_workspace_writable(bash):
    """Workspace /data is writable."""
    result = await bash.execute(
        command=(
            "echo 'test content' > /workspace/data/integration-test.txt && "
            "cat /workspace/data/integration-test.txt && "
            "rm /workspace/data/integration-test.txt"
        ),
        working_dir="/workspace",
    )
    assert result.success, f"Workspace not writable: {result.error}"
    assert "test content" in result.output["stdout"]


# ============================================================
# BASH + SEARXNG PIPELINE TESTS
# ============================================================


@pytest.mark.asyncio
async def test_bash_search(bash):
    """Bash can query SearXNG and parse results with jq."""
    result = await bash.execute(
        command=(
            "curl -s 'http://searxng:8080/search?q=python+programming&format=json' "
            "| jq '.results | length'"
        ),
        working_dir="/workspace",
    )
    assert result.success, f"Search via bash failed: {result.error}"
    count = result.output["stdout"].strip()
    assert count.isdigit() and int(count) > 0, (
        f"Expected positive result count, got: {count}"
    )


@pytest.mark.asyncio
async def test_bash_memory(bash):
    """Bash can write/read/cleanup memory files."""
    result = await bash.execute(
        command=(
            "echo '---\\ntags: [test]\\n---\\n# Integration Test' "
            "> /workspace/memory/general/test-integration.md && "
            "grep -l 'integration' /workspace/memory/general/ && "
            "rm /workspace/memory/general/test-integration.md"
        ),
        working_dir="/workspace",
    )
    assert result.success, f"Memory file ops failed: {result.error}"
    assert "test-integration.md" in result.output["stdout"]


@pytest.mark.asyncio
async def test_bash_script(bash):
    """Bash can write and execute a Python script."""
    result = await bash.execute(
        command=(
            "cat > /workspace/scripts/test-hello.py << 'PYEOF'\n"
            "print('hello from script')\n"
            "PYEOF\n"
            "python3 /workspace/scripts/test-hello.py && "
            "rm /workspace/scripts/test-hello.py"
        ),
        working_dir="/workspace",
    )
    assert result.success, f"Script execution failed: {result.error}"
    assert "hello from script" in result.output["stdout"]


@pytest.mark.asyncio
async def test_bash_chain(bash):
    """Bash can chain SearXNG search → file save → read."""
    result = await bash.execute(
        command=(
            "curl -s 'http://searxng:8080/search?q=python&format=json' "
            "| jq -r '.results[0].url' > /workspace/data/first-url.txt && "
            "cat /workspace/data/first-url.txt && "
            "rm /workspace/data/first-url.txt"
        ),
        working_dir="/workspace",
    )
    assert result.success, f"Chain failed: {result.error}"
    assert "http" in result.output["stdout"], (
        f"Expected URL in output, got: {result.output['stdout']}"
    )


# ============================================================
# SECURITY TESTS (work without Docker)
# ============================================================


@pytest.mark.asyncio
async def test_bash_security(bash, tmp_path):
    """Destructive rm -rf / is blocked."""
    result = await bash.execute(
        command="rm -rf /", working_dir=str(tmp_path)
    )
    assert not result.success
    assert "Blocked" in (result.error or "")


@pytest.mark.asyncio
async def test_bash_timeout(bash, tmp_path):
    """Commands exceeding timeout are killed."""
    result = await bash.execute(
        command="sleep 60", timeout=2, working_dir=str(tmp_path)
    )
    assert not result.success
    assert result.output["timed_out"] is True


# ============================================================
# WEB SEARCH FALLBACK TESTS
# ============================================================


@pytest.mark.asyncio
async def test_web_search_default_searxng(search):
    """WebSearchTool falls back to SearXNG when no SerpAPI cred."""
    result = await search.execute(query="python programming")
    assert result.success, f"Web search failed: {result.error}"
    assert len(result.output) > 0, "Expected at least one result"


@pytest.mark.asyncio
async def test_web_search_format(search):
    """Each web search result has title, url, snippet."""
    result = await search.execute(query="python programming", num_results=3)
    assert result.success, f"Web search failed: {result.error}"
    for item in result.output:
        assert "title" in item, f"Missing title in result: {item}"
        assert "url" in item, f"Missing url in result: {item}"
        assert "snippet" in item, f"Missing snippet in result: {item}"


# ============================================================
# END-TO-END TEST
# ============================================================


@pytest.mark.asyncio
async def test_search_save_find(bash):
    """Full pipeline: SearXNG search → save to file → verify content."""
    result = await bash.execute(
        command=(
            "curl -s 'http://searxng:8080/search?q=test&format=json' "
            "| jq '.results[0].title' > /workspace/data/search-result.txt && "
            "grep -c '.' /workspace/data/search-result.txt && "
            "rm /workspace/data/search-result.txt"
        ),
        working_dir="/workspace",
    )
    assert result.success, f"Search-save-find failed: {result.error}"
    # grep -c '.' returns count of non-empty lines
    count = result.output["stdout"].strip().split("\n")[-1]
    assert count.isdigit() and int(count) > 0, (
        f"Expected non-empty file, got line count: {count}"
    )
