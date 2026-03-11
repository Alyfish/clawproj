"""
Context Optimization Integration Tests — ClawBot v2.1

Verifies all context optimization strategies are working:
  - Save-to-file pattern (large results → disk)
  - Sub-agent scripts (Python scripts for multi-step work)
  - Progressive skill loading (INDEX.md, on-demand cat)
  - Session context (read-before-act verification)
  - Compaction (history → log files, tool result offloading)
  - Bash output hints (large output → save suggestion)
  - End-to-end context efficiency

Run with: pytest -m integration -v
Non-Docker tests also run in normal pytest.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from server.agent.context_builder import ContextBuilder
from server.agent.session_context import SessionContext
from server.agent.tools.bash_execute import BashExecuteTool
from server.agent.vfs import VFS


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with full VFS structure."""
    ws = tmp_path / "workspace"
    vfs = VFS(base=str(ws))
    vfs.init()
    return ws


@pytest.fixture
def vfs_with_skills(tmp_path: Path) -> tuple[VFS, Path]:
    """VFS with synced skills from a temporary skill source."""
    ws = tmp_path / "workspace"
    vfs = VFS(base=str(ws))
    vfs.init()

    # Create mock skill source with realistic content
    src = tmp_path / "skills_src"
    for name, desc, tags in [
        ("flight-search", "Search for flights across airlines", "flights, travel, booking"),
        ("apartment-search", "Find rental apartments", "apartments, rent, housing"),
        ("betting-odds", "Compare sports betting odds", "betting, sports, odds"),
        ("google-docs", "Create and edit Google Docs", "docs, google, writing"),
        ("price-monitor", "Monitor prices and set alerts", "prices, monitor, alerts"),
        ("skill-creator", "Create new skills", "skills, meta, creation"),
    ]:
        skill_dir = src / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {desc}\n"
            f"tags: [{tags}]\n---\n# {name}\n{desc}.\n\n"
            f"## Steps\n1. Search for data\n2. Parse results\n3. Present to user\n",
            encoding="utf-8",
        )

    vfs.sync_skills(str(src))
    return vfs, ws


@pytest.fixture
def bash() -> BashExecuteTool:
    return BashExecuteTool()


@pytest.fixture
def context_builder(workspace: Path, vfs_with_skills: tuple[VFS, Path]) -> ContextBuilder:
    """ContextBuilder with workspace path configured."""
    _, ws = vfs_with_skills
    return ContextBuilder(
        soul_path=str(ws / "SOUL.md"),  # won't exist, fallback used
        workspace_path=str(ws),
    )


# ============================================================
# SAVE-TO-FILE PATTERN TESTS
# ============================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_large_search_saved_to_file(bash: BashExecuteTool, workspace: Path) -> None:
    """Run SearXNG search saving to file → verify file exists, tool result is small."""
    data_dir = workspace / "data"
    result = await bash.execute(
        command=(
            "curl -s 'http://searxng:8080/search?q=python+programming&format=json' "
            f"> {data_dir}/search-results.json && "
            f"wc -c < {data_dir}/search-results.json"
        ),
        working_dir=str(workspace),
    )
    assert result.success, f"Search-save failed: {result.error}"
    # File should exist and have content
    saved = data_dir / "search-results.json"
    assert saved.exists(), "Search results not saved to file"
    assert saved.stat().st_size > 100, "Saved file is too small (empty results?)"
    # Tool result returned to conversation should be small (just byte count)
    stdout = result.output["stdout"]
    assert len(stdout) < 2000, f"Tool result too large ({len(stdout)} chars) — should be just the byte count"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_drill_down_from_saved_file(bash: BashExecuteTool, workspace: Path) -> None:
    """Save results → extract specific result with jq without reloading full data."""
    data_dir = workspace / "data"
    # Step 1: save full results
    r1 = await bash.execute(
        command=(
            "curl -s 'http://searxng:8080/search?q=python&format=json' "
            f"> {data_dir}/drill-results.json"
        ),
        working_dir=str(workspace),
    )
    assert r1.success, f"Save failed: {r1.error}"

    # Step 2: drill into specific field
    r2 = await bash.execute(
        command=f"jq '.results[0].title' {data_dir}/drill-results.json",
        working_dir=str(workspace),
    )
    assert r2.success, f"Drill-down failed: {r2.error}"
    assert len(r2.output["stdout"]) < 500, "Drill-down output should be small"


# ============================================================
# SUB-AGENT SCRIPT TESTS
# ============================================================


@pytest.mark.asyncio
async def test_compare_script_single_call(bash: BashExecuteTool, workspace: Path) -> None:
    """Write and run a comparison script in one bash_execute call."""
    scripts_dir = workspace / "scripts"
    data_dir = workspace / "data"

    result = await bash.execute(
        command=(
            f"cat > {scripts_dir}/compare-prices.py << 'PYEOF'\n"
            "import json\n"
            "prices = [\n"
            '    {"source": "StockX", "price": 168},\n'
            '    {"source": "GOAT", "price": 175},\n'
            '    {"source": "eBay", "price": 182},\n'
            "]\n"
            f'with open("{data_dir}/price-comparison.json", "w") as f:\n'
            "    json.dump(prices, f)\n"
            "cheapest = min(prices, key=lambda x: x['price'])\n"
            "print(f\"Cheapest: ${cheapest['price']} on {cheapest['source']}\")\n"
            "PYEOF\n"
            f"python3 {scripts_dir}/compare-prices.py"
        ),
        working_dir=str(workspace),
    )
    assert result.success, f"Script execution failed: {result.error}"

    # Script should exist at /workspace/scripts/
    assert (scripts_dir / "compare-prices.py").exists(), "Script not saved"

    # Output should be a clean summary
    stdout = result.output["stdout"].strip()
    assert len(stdout) < 500, f"Output too large ({len(stdout)} bytes)"
    assert "Cheapest" in stdout

    # Full data should be saved to /workspace/data/
    assert (data_dir / "price-comparison.json").exists(), "Data not saved"


@pytest.mark.asyncio
async def test_script_reuse(bash: BashExecuteTool, workspace: Path) -> None:
    """Create a script → verify it persists → run again with different params."""
    scripts_dir = workspace / "scripts"

    # Create the script
    r1 = await bash.execute(
        command=(
            f"cat > {scripts_dir}/greet.py << 'PYEOF'\n"
            "import sys\n"
            "name = sys.argv[1] if len(sys.argv) > 1 else 'World'\n"
            "print(f'Hello, {name}!')\n"
            "PYEOF\n"
            f"python3 {scripts_dir}/greet.py Alice"
        ),
        working_dir=str(workspace),
    )
    assert r1.success
    assert "Hello, Alice!" in r1.output["stdout"]

    # Verify script persists
    assert (scripts_dir / "greet.py").exists()

    # Run again with different params
    r2 = await bash.execute(
        command=f"python3 {scripts_dir}/greet.py Bob",
        working_dir=str(workspace),
    )
    assert r2.success
    assert "Hello, Bob!" in r2.output["stdout"]


# ============================================================
# PROGRESSIVE SKILL LOADING TESTS
# ============================================================


def test_system_prompt_has_no_skill_content(
    vfs_with_skills: tuple[VFS, Path],
) -> None:
    """System prompt should NOT contain full skill text — only INDEX.md pointer."""
    vfs, ws = vfs_with_skills
    builder = ContextBuilder(
        soul_path=str(ws / "nonexistent-soul.md"),  # force fallback
        workspace_path=str(ws),
    )
    prompt = builder.build_system_prompt()

    # Should NOT contain full skill content
    assert "## Steps" not in prompt, "Full skill content leaked into system prompt"
    assert "Parse results" not in prompt, "Skill instructions leaked into prompt"

    # SHOULD contain INDEX.md reference
    assert "INDEX.md" in prompt, "Missing INDEX.md reference in prompt"
    assert "skills" in prompt.lower(), "Missing skills reference in prompt"


def test_skill_index_valid(vfs_with_skills: tuple[VFS, Path]) -> None:
    """INDEX.md lists all expected skills with valid paths."""
    vfs, ws = vfs_with_skills
    index_path = ws / "skills" / "INDEX.md"
    assert index_path.exists(), "INDEX.md not generated"

    content = index_path.read_text(encoding="utf-8")
    expected_skills = [
        "flight-search", "apartment-search", "betting-odds",
        "google-docs", "price-monitor", "skill-creator",
    ]
    for skill in expected_skills:
        assert skill in content, f"Skill '{skill}' missing from INDEX.md"

    # Verify each referenced SKILL.md file actually exists
    for skill in expected_skills:
        skill_file = ws / "skills" / skill / "SKILL.md"
        assert skill_file.exists(), f"SKILL.md missing for {skill}"


@pytest.mark.asyncio
async def test_skill_loaded_on_demand(
    bash: BashExecuteTool,
    vfs_with_skills: tuple[VFS, Path],
) -> None:
    """Simulate loading a skill via bash cat — returns content matching original."""
    _, ws = vfs_with_skills
    skill_path = ws / "skills" / "flight-search" / "SKILL.md"

    result = await bash.execute(
        command=f"cat {skill_path}",
        working_dir=str(ws),
    )
    assert result.success, f"Skill cat failed: {result.error}"
    stdout = result.output["stdout"]
    assert "flight-search" in stdout, "Skill content doesn't match"
    assert "Search for flights" in stdout, "Skill description missing"


# ============================================================
# SESSION CONTEXT TESTS
# ============================================================


def test_session_tracks_search() -> None:
    """Record bash with 'curl searxng' → has_searched() True."""
    ctx = SessionContext()
    ctx.record_tool_call("bash_execute", "curl -s 'http://searxng:8080/search?q=test&format=json'")
    assert ctx.has_searched()


def test_card_warning_without_search() -> None:
    """Empty context → create_card check → warning injected."""
    ctx = SessionContext()
    warning = ctx.check_card_data("flight", {})
    assert warning is not None
    assert "VERIFICATION REQUIRED" in warning


def test_payment_blocked_without_verification() -> None:
    """Empty context → request_approval('pay') → blocked."""
    ctx = SessionContext()
    rejection = ctx.check_payment_readiness()
    assert rejection is not None
    assert "PAYMENT BLOCKED" in rejection


def test_payment_allowed_after_search() -> None:
    """Record search → request_approval('pay') → allowed."""
    ctx = SessionContext()
    ctx.record_tool_call("web_search", "cheapest sneakers")
    rejection = ctx.check_payment_readiness()
    assert rejection is None


# ============================================================
# COMPACTION TESTS
# ============================================================


def test_compaction_saves_history(workspace: Path) -> None:
    """Mock 130K tokens → trigger compaction → verify log file + summary."""
    builder = ContextBuilder(
        soul_path=str(workspace / "nonexistent.md"),
        workspace_path=str(workspace),
        max_tokens=1000,  # low threshold to force compaction
        keep_recent=3,
    )

    # Build history with enough content to exceed threshold
    messages: list[dict] = []
    for i in range(20):
        messages.append({"role": "user", "content": f"User message {i}: " + "x" * 500})
        messages.append({"role": "assistant", "content": f"Assistant response {i}: " + "y" * 500})

    compacted = builder.compact_history(messages)

    # Should have kept recent + summary
    assert len(compacted) < len(messages), "Compaction didn't reduce messages"
    assert len(compacted) >= 3, "Too few messages after compaction"

    # Log file should exist
    logs_dir = workspace / "logs"
    log_files = list(logs_dir.glob("session-*.md"))
    assert len(log_files) > 0, "No compaction log file created"

    # Log file should contain conversation content
    log_content = log_files[0].read_text(encoding="utf-8")
    assert "User message" in log_content
    assert "Assistant response" in log_content

    # Summary message should reference the log file
    summary_content = compacted[0]["content"]
    assert "session-" in summary_content or "Summary" in summary_content


def test_tool_result_offloading(workspace: Path) -> None:
    """10KB tool result → offloaded to file → replaced with reference."""
    builder = ContextBuilder(
        soul_path=str(workspace / "nonexistent.md"),
        workspace_path=str(workspace),
    )

    large_content = "x" * 10_000
    messages = [
        {"role": "user", "content": "search for something"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tool_1", "name": "bash_execute", "input": {"command": "echo hi"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tool_1", "content": large_content},
        ]},
    ]

    builder._offload_large_tool_results(messages)

    # Tool result should be replaced with file reference
    result_content = messages[2]["content"][0]["content"]
    assert "saved to" in result_content.lower() or "Output saved" in result_content
    assert len(result_content) < 500, f"Offloaded reference too large: {len(result_content)}"

    # File should exist in /workspace/data/
    data_files = list((workspace / "data").glob("tool-result-*.json"))
    assert len(data_files) > 0, "No offloaded tool result file"

    # File should contain original content
    file_content = data_files[0].read_text(encoding="utf-8")
    assert file_content == large_content


def test_small_results_not_offloaded(workspace: Path) -> None:
    """500B tool result stays in history — not offloaded."""
    builder = ContextBuilder(
        soul_path=str(workspace / "nonexistent.md"),
        workspace_path=str(workspace),
    )

    small_content = "result data: " + "x" * 400
    messages = [
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tool_2", "name": "bash_execute", "input": {"command": "echo hi"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tool_2", "content": small_content},
        ]},
    ]

    builder._offload_large_tool_results(messages)

    # Content should remain unchanged
    result_content = messages[2]["content"][0]["content"]
    assert result_content == small_content, "Small result was incorrectly offloaded"

    # No files should be created
    data_files = list((workspace / "data").glob("tool-result-*.json"))
    assert len(data_files) == 0, "Unexpected offload file for small result"


# ============================================================
# BASH HINT TESTS
# ============================================================


@pytest.mark.asyncio
async def test_large_output_gets_hint(bash: BashExecuteTool, workspace: Path) -> None:
    """bash_execute generating >5KB output → result contains hint about saving."""
    result = await bash.execute(
        command="python3 -c \"print('x' * 6000)\"",
        working_dir=str(workspace),
    )
    assert result.success
    stdout = result.output["stdout"]
    assert "Hint" in stdout or "hint" in stdout.lower() or "save" in stdout.lower(), (
        "Large output should include a hint about saving to file"
    )


@pytest.mark.asyncio
async def test_small_output_no_hint(bash: BashExecuteTool, workspace: Path) -> None:
    """bash_execute('echo hello') → no hint in result."""
    result = await bash.execute(
        command="echo hello",
        working_dir=str(workspace),
    )
    assert result.success
    stdout = result.output["stdout"]
    assert "Hint" not in stdout and "[Warning" not in stdout, (
        "Small output should not have save hints"
    )


# ============================================================
# END-TO-END CONTEXT TEST
# ============================================================


@pytest.mark.asyncio
async def test_full_session_context_efficiency(
    bash: BashExecuteTool,
    workspace: Path,
) -> None:
    """Simulate multi-task session → total tool result bytes stays small."""
    scripts_dir = workspace / "scripts"
    data_dir = workspace / "data"
    total_result_bytes = 0

    # 1. Search for sneaker prices (bash) — save to file
    r1 = await bash.execute(
        command=(
            f"echo '{{\"results\": [{{\"title\": \"Jordan 11\", \"price\": 168}}]}}' "
            f"> {data_dir}/sneakers.json && echo 'Saved sneaker data'"
        ),
        working_dir=str(workspace),
    )
    assert r1.success
    total_result_bytes += len(r1.output["stdout"])

    # 2. Create a comparison script
    r2 = await bash.execute(
        command=(
            f"cat > {scripts_dir}/analyze-prices.py << 'PYEOF'\n"
            "import json, sys\n"
            f"data = json.load(open('{data_dir}/sneakers.json'))\n"
            "print(f\"Found {{len(data['results'])}} results\")\n"
            "PYEOF\n"
            "echo 'Script created'"
        ),
        working_dir=str(workspace),
    )
    assert r2.success
    total_result_bytes += len(r2.output["stdout"])

    # 3. Run the script
    r3 = await bash.execute(
        command=f"python3 {scripts_dir}/analyze-prices.py",
        working_dir=str(workspace),
    )
    assert r3.success
    total_result_bytes += len(r3.output["stdout"])

    # 4. Verify files exist
    r4 = await bash.execute(
        command=f"ls {data_dir}/sneakers.json {scripts_dir}/analyze-prices.py",
        working_dir=str(workspace),
    )
    assert r4.success
    total_result_bytes += len(r4.output["stdout"])

    # Total tool results in conversation should be small
    assert total_result_bytes < 5000, (
        f"Total tool result bytes ({total_result_bytes}) exceeds 5KB threshold. "
        "Context optimization should keep results small by saving to files."
    )
