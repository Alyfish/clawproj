"""
ClawBot Agent v2 — Entry Point

Wires all components together and runs the agentic loop.

Usage:
  python -m server.agent.main              # Connect to gateway
  python -m server.agent.main --test       # Test mode (stdin/stdout)
  python -m server.agent.main --test -v    # Test mode + debug logging
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from .config import AgentConfig
from .agent import Agent
from .gateway_client import GatewayClient, MockGatewayClient
from .context_builder import ContextBuilder
from .memory import MemoryManager, AsyncMemoryAdapter
from .skill_loader import SkillLoader
from .skill_registry import SkillRegistry
from .credential_store import CredentialStore
from .tools.register import create_registry
from .vfs import VFS


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


async def main(args: argparse.Namespace) -> None:
    # 1. Load config
    config = AgentConfig()
    if args.test:
        config.test_mode = True
    if args.mock:
        config.mock_tools = True
    if args.model:
        config.model = args.model

    # 2. Validate
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    print("ClawBot Agent v2")
    print(f"   Model: {config.model}")
    print(f"   Mode: {'test (stdin/stdout)' if config.test_mode else 'gateway'}")
    print(f"   Max iterations: {config.max_iterations}")
    print()

    # 3. Initialize components
    # Filesystem
    vfs = VFS()
    vfs.init()
    print(f"   Workspace: {vfs.base}")

    # Skills
    skill_loader = SkillLoader(config.skills_dir)
    skill_registry = SkillRegistry(skill_loader)
    vfs.sync_skills(config.skills_dir)
    print(f"   Skills synced to: {vfs.base}/skills/")

    # Memory
    memory_manager = MemoryManager(vfs.resolve("memory"))
    memory_adapter = AsyncMemoryAdapter(memory_manager)
    print(f"   Memory: {vfs.resolve('memory')}")

    # Credentials
    credential_store = CredentialStore(config.credentials_path)
    print(f"   Credentials: {config.credentials_path}")

    # Tools (async adapter for save/search tools)
    tool_registry, login_flow_manager = create_registry(
        gateway_client=None,  # set after gateway init
        memory_system=memory_adapter,
        credential_store=credential_store.get_for_tool,
        site_login_lookup=credential_store.get_site_login,
    )

    # Context (sync MemoryStore satisfies MemorySystemProtocol)
    context_builder = ContextBuilder(
        soul_path=config.soul_path,
        skill_registry=skill_registry,
        memory_system=memory_manager.store,
        workspace_path=vfs.base,
    )

    # Context tools — populate <available_tools> section in system prompt
    context_builder.set_tools(tool_registry.get_tool_definitions())

    # Gateway client
    if config.test_mode:
        gateway: GatewayClient | MockGatewayClient = MockGatewayClient()
    else:
        gateway = GatewayClient(config)

    # Wire gateway to tools that need it (create_card, request_approval)
    tool_registry.set_gateway_client(gateway)

    # Wire gateway to login flow manager (created before gateway existed)
    if login_flow_manager is not None:
        login_flow_manager._gateway = gateway

    # 4. Create the agent
    agent = Agent(
        config=config,
        gateway_client=gateway,
        context_builder=context_builder,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
        login_flow_manager=login_flow_manager,
    )

    # 5. Connect and run
    await gateway.connect()

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def handle_signal(sig: signal.Signals) -> None:
        print(f"\n[Received {sig.name}, shutting down...]")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal, sig)

    try:
        # Run agent until shutdown
        agent_task = asyncio.create_task(agent.run())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        done, pending = await asyncio.wait(
            [agent_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    finally:
        await agent.shutdown()
        await gateway.disconnect()
        print("ClawBot shut down cleanly")


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="ClawBot Agent v2 — The Agentic Loop",
    )
    parser.add_argument(
        "--test", "-t", action="store_true",
        help="Test mode: read from stdin, write to stdout (no gateway)",
    )
    parser.add_argument(
        "--mock", "-m", action="store_true",
        help="Use mock tool results (for testing without real APIs)",
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Override Claude model (default: claude-sonnet-4-5-20250929)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
