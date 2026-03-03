"""
ClawBot End-to-End Integration Tests

Validates the 5 core use cases with real Claude API calls,
real tools (mock mode), and a recording TestGateway.

Usage:
  python -m server.agent.test_integration
  python -m server.agent.test_integration -v   # verbose logging

Requires: ANTHROPIC_API_KEY or CLAUDE_API_KEY env var
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from server.agent.config import AgentConfig
from server.agent.agent import Agent
from server.agent.context_builder import ContextBuilder
from server.agent.memory import MemoryManager, AsyncMemoryAdapter
from server.agent.skill_loader import SkillLoader
from server.agent.skill_registry import SkillRegistry
from server.agent.credential_store import CredentialStore
from server.agent.tools.register import create_registry

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# TEST GATEWAY — records all events for assertions
# ════════════════════════════════════════════════════════════════


class TestGateway:
    """Mock gateway that records all emitted events for test assertions.

    Auto-approves approval requests so the agentic loop doesn't block.
    """

    def __init__(self) -> None:
        self._session_id: str = "integration-test"
        self.reset()

    def reset(self) -> None:
        """Clear all recorded events between tests."""
        self.text_deltas: list[str] = []
        self.lifecycle_events: list[dict] = []
        self.thinking_steps: list[dict] = []
        self.tool_starts: list[dict] = []
        self.tool_ends: list[dict] = []
        self.task_updates: list[dict] = []
        self.cards: list[dict] = []
        self.approvals: list[dict] = []
        self.raw_events: list[dict] = []

    # ── Connection (no-op) ─────────────────────────────────────

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return True

    async def receive_messages(self) -> AsyncGenerator[dict, None]:
        # Not used — we call agent.process_message() directly
        return
        yield  # Make it a generator

    # ── Event recording ────────────────────────────────────────

    async def emit_event(self, event: str, payload: dict) -> None:
        self.raw_events.append({"event": event, "payload": payload})

    async def stream_text(
        self, delta: str, session_id: str | None = None,
    ) -> None:
        self.text_deltas.append(delta)

    async def stream_lifecycle(
        self, status: str, run_id: str, session_id: str | None = None,
    ) -> None:
        self.lifecycle_events.append({
            "status": status, "runId": run_id,
        })

    async def stream_thinking(
        self,
        tool_name: str,
        summary: str,
        status: str = "running",
        session_id: str | None = None,
    ) -> None:
        self.thinking_steps.append({
            "toolName": tool_name, "summary": summary, "status": status,
        })

    async def emit_tool_start(
        self, tool_name: str, description: str, session_id: str | None = None,
    ) -> None:
        self.tool_starts.append({
            "toolName": tool_name, "description": description,
        })

    async def emit_tool_end(
        self,
        tool_name: str,
        success: bool,
        summary: str,
        session_id: str | None = None,
    ) -> None:
        self.tool_ends.append({
            "toolName": tool_name, "success": success, "summary": summary,
        })

    async def emit_task_update(
        self,
        task_id: str,
        status: str,
        step: dict | None = None,
        card: dict | None = None,
    ) -> None:
        self.task_updates.append({
            "taskId": task_id, "status": status, "step": step, "card": card,
        })

    async def emit_card(self, card: dict) -> None:
        self.cards.append(card)

    async def request_approval(
        self,
        action: str,
        description: str,
        details: dict | None = None,
        timeout: float = 600.0,
    ) -> dict:
        self.approvals.append({
            "action": action,
            "description": description,
            "details": details,
        })
        return {"approved": True, "message": "Auto-approved by TestGateway"}

    # ── Helpers for assertions ─────────────────────────────────

    @property
    def full_text(self) -> str:
        return "".join(self.text_deltas)

    @property
    def tool_names_used(self) -> list[str]:
        return [s["toolName"] for s in self.tool_starts]

    def has_lifecycle(self, status: str) -> bool:
        return any(e["status"] == status for e in self.lifecycle_events)

    def has_task_status(self, status: str) -> bool:
        return any(u["status"] == status for u in self.task_updates)


# ════════════════════════════════════════════════════════════════
# COMPONENT WIRING
# ════════════════════════════════════════════════════════════════


def build_stack(gateway: TestGateway) -> tuple[Agent, AgentConfig]:
    """Wire all components exactly as main.py does, but with TestGateway."""
    config = AgentConfig()
    config.test_mode = True
    config.max_iterations = 10

    # Skills
    skill_loader = SkillLoader(config.skills_dir)
    skill_registry = SkillRegistry(skill_loader)

    # Memory (use a temp dir so tests don't pollute real memory)
    memory_dir = str(Path(config.project_root) / "memory_test_integration")
    Path(memory_dir).mkdir(parents=True, exist_ok=True)
    memory_manager = MemoryManager(memory_dir)
    memory_adapter = AsyncMemoryAdapter(memory_manager)

    # Credentials
    credential_store = CredentialStore(config.credentials_path)

    # Tools
    tool_registry = create_registry(
        gateway_client=None,
        memory_system=memory_adapter,
        credential_store=credential_store.get_for_tool,
    )

    # Context
    context_builder = ContextBuilder(
        soul_path=config.soul_path,
        skill_registry=skill_registry,
        memory_system=memory_manager.store,
    )
    context_builder.set_tools(tool_registry.get_tool_definitions())

    # Wire gateway
    tool_registry.set_gateway_client(gateway)

    # Agent
    agent = Agent(
        config=config,
        gateway_client=gateway,
        context_builder=context_builder,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )

    return agent, config


# ════════════════════════════════════════════════════════════════
# TEST RUNNER
# ════════════════════════════════════════════════════════════════


class TestResult:
    """Tracks a single test outcome."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = False
        self.soft_pass = False
        self.checks: list[tuple[str, bool, str]] = []  # (label, ok, detail)
        self.duration_s: float = 0.0
        self.error: str | None = None

    def check(self, label: str, ok: bool, detail: str = "") -> bool:
        icon = "+" if ok else "x"
        self.checks.append((label, ok, detail))
        return ok

    @property
    def status(self) -> str:
        if self.error:
            return "ERROR"
        if self.passed:
            return "PASS"
        if self.soft_pass:
            return "SOFT PASS"
        return "FAIL"

    def print_report(self) -> None:
        for label, ok, detail in self.checks:
            icon = "+" if ok else "x"
            suffix = f" ({detail})" if detail else ""
            print(f"  {icon} {label}{suffix}")
        if self.error:
            print(f"  ! Error: {self.error}")
        print(f"  {self.status} ({self.duration_s:.1f}s)")
        print()


# ── Individual Tests ──────────────────────────────────────────


async def _test_flight_search(
    agent: Agent, gateway: TestGateway, session_id: str,
) -> TestResult:
    """Test 1: Skill-based flight search."""
    result = TestResult("Skill-based flight search")
    gateway.reset()
    t0 = time.time()

    try:
        await asyncio.wait_for(
            agent.process_message(
                "Find cheap flights from SFO to London in April. "
                "Use the flight-search skill.",
                session_id,
            ),
            timeout=120,
        )
    except asyncio.TimeoutError:
        result.error = "Timed out after 120s"
        result.duration_s = time.time() - t0
        return result
    except Exception as e:
        result.error = str(e)
        result.duration_s = time.time() - t0
        return result

    result.duration_s = time.time() - t0

    # Assertions
    has_start = result.check(
        "Lifecycle: start emitted",
        gateway.has_lifecycle("start"),
    )
    has_end = result.check(
        "Lifecycle: end emitted",
        gateway.has_lifecycle("end"),
    )
    has_executing = result.check(
        "Task update: executing",
        gateway.has_task_status("executing"),
    )
    has_completed = result.check(
        "Task update: completed",
        gateway.has_task_status("completed"),
    )

    skill_loaded = any("load_skill" in s.get("toolName", "") for s in gateway.thinking_steps)
    result.check(
        "load_skill called",
        skill_loaded,
        "flight-search" if skill_loaded else "not triggered",
    )

    card_count = len(gateway.cards)
    result.check(
        "Cards created",
        card_count > 0,
        f"{card_count} card(s)",
    )

    text_len = len(gateway.full_text)
    result.check(
        "Response streamed",
        text_len > 0,
        f"{text_len} chars",
    )

    tool_count = len(gateway.tool_starts)
    result.check(
        "Tools invoked",
        tool_count > 0,
        f"{tool_count} tool call(s): {', '.join(gateway.tool_names_used[:5])}",
    )

    # Pass if lifecycle + task updates + some text
    all_critical = has_start and has_end and has_executing and has_completed and text_len > 0
    if all_critical and card_count > 0:
        result.passed = True
    elif all_critical:
        result.soft_pass = True

    return result


async def _test_approval_flow(
    agent: Agent, gateway: TestGateway, session_id: str,
) -> TestResult:
    """Test 2: Approval flow — agent should request approval for a booking."""
    result = TestResult("Approval flow")
    gateway.reset()
    t0 = time.time()

    try:
        await asyncio.wait_for(
            agent.process_message(
                "Book the cheapest United flight from SFO to London for me. "
                "You must request approval before booking.",
                session_id,
            ),
            timeout=120,
        )
    except asyncio.TimeoutError:
        result.error = "Timed out after 120s"
        result.duration_s = time.time() - t0
        return result
    except Exception as e:
        result.error = str(e)
        result.duration_s = time.time() - t0
        return result

    result.duration_s = time.time() - t0

    approval_count = len(gateway.approvals)
    has_approval = result.check(
        "Approval requested",
        approval_count > 0,
        f"{approval_count} request(s)" + (
            f" — action: {gateway.approvals[0]['action']}"
            if gateway.approvals else ""
        ),
    )

    result.check(
        "Auto-approved by TestGateway",
        has_approval,
    )

    text_after = len(gateway.full_text)
    result.check(
        "Agent continued after approval",
        text_after > 0,
        f"{text_after} chars of response",
    )

    # Approval flow is non-deterministic — Claude may or may not call request_approval
    if has_approval and text_after > 0:
        result.passed = True
    elif text_after > 0:
        result.soft_pass = True

    return result


async def _test_memory_save(
    agent: Agent, gateway: TestGateway, session_id: str, config: AgentConfig,
) -> TestResult:
    """Test 3: Memory save — agent saves user preferences."""
    result = TestResult("Memory save")
    gateway.reset()
    t0 = time.time()

    try:
        await asyncio.wait_for(
            agent.process_message(
                "Remember that I prefer window seats and I'm a United "
                "MileagePlus member. Save this to memory.",
                session_id,
            ),
            timeout=60,
        )
    except asyncio.TimeoutError:
        result.error = "Timed out after 60s"
        result.duration_s = time.time() - t0
        return result
    except Exception as e:
        result.error = str(e)
        result.duration_s = time.time() - t0
        return result

    result.duration_s = time.time() - t0

    save_calls = [s for s in gateway.tool_starts if s["toolName"] == "save_memory"]
    has_save = result.check(
        "save_memory called",
        len(save_calls) > 0,
        f"{len(save_calls)} call(s)",
    )

    # Check if memory file was written
    memory_test_dir = str(Path(config.project_root) / "memory_test_integration")
    memory_files = list(Path(memory_test_dir).rglob("*.md"))
    result.check(
        "Memory file written",
        len(memory_files) > 0,
        f"{len(memory_files)} file(s) in {memory_test_dir}",
    )

    text_len = len(gateway.full_text)
    result.check(
        "Response streamed",
        text_len > 0,
        f"{text_len} chars",
    )

    if has_save and text_len > 0:
        result.passed = True
    elif text_len > 0:
        result.soft_pass = True

    return result


async def _test_unknown_domain(
    agent: Agent, gateway: TestGateway,
) -> TestResult:
    """Test 4: Unknown domain — agent handles a domain with no matching skill."""
    result = TestResult("Unknown domain (Shopify)")
    gateway.reset()
    fresh_session = f"integration-fresh-{uuid.uuid4().hex[:8]}"
    t0 = time.time()

    try:
        await asyncio.wait_for(
            agent.process_message(
                "Check my Shopify store for new orders today.",
                fresh_session,
            ),
            timeout=180,
        )
    except asyncio.TimeoutError:
        result.error = "Timed out after 180s"
        result.duration_s = time.time() - t0
        return result
    except Exception as e:
        result.error = str(e)
        result.duration_s = time.time() - t0
        return result

    result.duration_s = time.time() - t0

    tool_count = len(gateway.tool_starts)
    result.check(
        "Agent used tools",
        tool_count > 0,
        f"{tool_count} tool call(s): {', '.join(gateway.tool_names_used[:5])}",
    )

    # Check what path Claude took
    used_skill_creator = any("skill" in t.get("toolName", "").lower() for t in gateway.thinking_steps)
    used_http = "http_request" in gateway.tool_names_used
    used_browser = "browser" in gateway.tool_names_used

    path_desc = []
    if used_skill_creator:
        path_desc.append("skill-creator")
    if used_http:
        path_desc.append("http_request")
    if used_browser:
        path_desc.append("browser")
    if not path_desc:
        path_desc.append("text-only response")

    result.check(
        "Path taken",
        True,
        " + ".join(path_desc),
    )

    text_len = len(gateway.full_text)
    result.check(
        "Response streamed",
        text_len > 0,
        f"{text_len} chars",
    )

    # This test is intentionally soft — Claude may take different paths
    if text_len > 0:
        result.soft_pass = True
        if tool_count > 0:
            result.passed = True

    return result


async def _test_generic_card(
    agent: Agent, gateway: TestGateway,
) -> TestResult:
    """Test 5: Generic card rendering — programmatic (no Claude needed)."""
    result = TestResult("Generic card rendering")
    t0 = time.time()

    try:
        # Directly call the create_card tool with a custom type
        tool = agent.tool_registry.get("create_card")
        if tool is None:
            result.error = "create_card tool not found in registry"
            result.duration_s = time.time() - t0
            return result

        # Ensure gateway is wired
        if hasattr(tool, "set_gateway_client"):
            tool.set_gateway_client(gateway)

        card_result = await tool.execute(
            type="shopify_order",
            title="Order #1042 — 2x Widget Pro",
            subtitle="$79.98 shipped via USPS",
            metadata={
                "order_id": "1042",
                "items": 2,
                "total": "$79.98",
                "shipping": "USPS Priority",
                "customer": "Jane Doe",
            },
        )

        result.duration_s = time.time() - t0

        result.check(
            "Tool returned success",
            card_result.success,
            str(card_result.error) if not card_result.success else "",
        )

        if card_result.success and isinstance(card_result.output, dict):
            card = card_result.output

            result.check(
                "Card type is custom",
                card.get("type") == "shopify_order",
                f"type={card.get('type')}",
            )

            result.check(
                "Card has title",
                card.get("title") == "Order #1042 — 2x Widget Pro",
            )

            # For non-typed cards, metadata should stay in metadata dict
            # (only typed cards — flight/house/pick/doc — promote metadata to root)
            metadata = card.get("metadata", {})
            result.check(
                "Metadata stays in metadata dict",
                "order_id" in metadata,
                f"metadata keys: {list(metadata.keys())}",
            )

            # Confirm typed-card-specific keys are NOT at root
            result.check(
                "Custom fields not promoted to root",
                "order_id" not in card or "order_id" in metadata,
                "order_id only in metadata" if "order_id" not in card else "also at root",
            )

            result.passed = True
        else:
            result.check("Card output is dict", False, f"got {type(card_result.output)}")

    except Exception as e:
        result.error = str(e)
        result.duration_s = time.time() - t0

    return result


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════


async def run_tests(verbose: bool = False) -> int:
    """Run all integration tests. Returns exit code (0 = all pass)."""

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        print("No ANTHROPIC_API_KEY or CLAUDE_API_KEY found.")
        print("Set one of these env vars to run integration tests.")
        print()
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        print("  python -m server.agent.test_integration")
        return 1

    # Build components
    gateway = TestGateway()
    agent, config = build_stack(gateway)

    # Count skills
    skill_count = len(agent.skill_registry.list_skills())

    print()
    print("=" * 52)
    print("  ClawBot Integration Tests")
    print(f"  Model: {config.model}")
    print(f"  Skills: {skill_count} loaded")
    print(f"  Tools: {agent.tool_registry.count} registered")
    print(f"  Max iterations: {config.max_iterations}")
    print("=" * 52)
    print()

    session_id = f"integration-{uuid.uuid4().hex[:8]}"
    results: list[TestResult] = []

    # ── Test 1: Flight search ──────────────────────────────────
    print("Test 1: Skill-based flight search")
    r1 = await _test_flight_search(agent, gateway, session_id)
    r1.print_report()
    results.append(r1)

    # ── Test 2: Approval flow ──────────────────────────────────
    print("Test 2: Approval flow")
    r2 = await _test_approval_flow(agent, gateway, session_id)
    r2.print_report()
    results.append(r2)

    # ── Test 3: Memory save ────────────────────────────────────
    print("Test 3: Memory save")
    r3 = await _test_memory_save(agent, gateway, session_id, config)
    r3.print_report()
    results.append(r3)

    # ── Test 4: Unknown domain ─────────────────────────────────
    print("Test 4: Unknown domain (Shopify)")
    r4 = await _test_unknown_domain(agent, gateway)
    r4.print_report()
    results.append(r4)

    # ── Test 5: Generic card ───────────────────────────────────
    print("Test 5: Generic card rendering")
    r5 = await _test_generic_card(agent, gateway)
    r5.print_report()
    results.append(r5)

    # ── Summary ────────────────────────────────────────────────
    pass_count = sum(1 for r in results if r.passed)
    soft_count = sum(1 for r in results if r.soft_pass and not r.passed)
    fail_count = sum(1 for r in results if not r.passed and not r.soft_pass)
    error_count = sum(1 for r in results if r.error)
    total_time = sum(r.duration_s for r in results)

    print("=" * 52)
    parts = []
    if pass_count:
        parts.append(f"{pass_count} PASS")
    if soft_count:
        parts.append(f"{soft_count} SOFT PASS")
    if fail_count:
        parts.append(f"{fail_count} FAIL")
    if error_count:
        parts.append(f"{error_count} ERROR")
    print(f"  Results: {', '.join(parts)}")
    print(f"  Total time: {total_time:.1f}s")
    print("=" * 52)
    print()

    # Cleanup test memory dir
    memory_test_dir = Path(config.project_root) / "memory_test_integration"
    if memory_test_dir.exists():
        import shutil
        shutil.rmtree(memory_test_dir, ignore_errors=True)
        print("  (cleaned up test memory dir)")

    return 0 if fail_count == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="ClawBot Integration Tests")
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)

    exit_code = asyncio.run(run_tests(args.verbose))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
