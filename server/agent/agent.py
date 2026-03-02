"""
ClawBot Agentic Loop

THE core brain. Pattern:
  receive message → build context → call Claude with streaming →
  if tool_use, execute tools and loop → if done, respond.

References:
  - claw0 sessions/en/s01_agent_loop.py (while True + stop_reason)
  - learn-claude-code v1_basic_agent.py (tool dispatch loop)
  - OpenManus app/agent/toolcall.py (think → act → observe cycle)
  - anthropic-sdk-python helpers.md (streaming API)
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import anthropic

from server.agent.config import AgentConfig
from server.agent.context_builder import ContextBuilder
from server.agent.helpers import describe_tool_call, generate_run_id, summarize_result
from server.agent.skill_registry import (
    LOAD_SKILL_TOOL,
    SkillRegistry,
    execute_load_skill,
)
from server.agent.tools.tool_registry import ToolRegistry, ToolResult, truncate

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────

MAX_TOOL_RESULT_CHARS = 50_000
MAX_RETRIES = 3


# ── Schema conversion ────────────────────────────────────────

def _convert_params_to_json_schema(clawbot_params: dict[str, Any]) -> dict[str, Any]:
    """Convert ClawBot's custom param format to Claude API JSON Schema.

    ClawBot: {"param": {"type": "string", "required": True, "description": "..."}}
    Claude:  {"type": "object", "properties": {"param": {"type": "string", ...}}, "required": ["param"]}
    """
    if not clawbot_params:
        return {"type": "object", "properties": {}}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param_def in clawbot_params.items():
        cleaned = dict(param_def)  # shallow copy
        if cleaned.pop("required", False):
            required.append(param_name)
        properties[param_name] = cleaned

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _format_tool_result_content(result: ToolResult) -> str:
    """Convert ToolResult to string for Claude's tool_result content block."""
    if not result.success and result.error:
        if result.output:
            text = f"Error: {result.error}\nOutput: {json.dumps(result.output, default=str)}"
        else:
            text = f"Error: {result.error}"
        return truncate(text, MAX_TOOL_RESULT_CHARS)

    output = result.output
    if isinstance(output, (dict, list)):
        text = json.dumps(output, ensure_ascii=False, default=str)
    elif output is None:
        text = "(no output)"
    else:
        text = str(output)

    return truncate(text, MAX_TOOL_RESULT_CHARS)


# ── Agent ─────────────────────────────────────────────────────

class Agent:
    """
    The ClawBot Agentic Loop.

    Pattern:
      receive message → build context → call LLM → if tool_use,
      execute tools → loop → respond.
    """

    def __init__(
        self,
        config: AgentConfig,
        gateway_client: Any,
        context_builder: ContextBuilder,
        skill_registry: SkillRegistry,
        tool_registry: ToolRegistry,
    ) -> None:
        self.config = config
        self.gateway = gateway_client
        self.context_builder = context_builder
        self.skill_registry = skill_registry
        self.tool_registry = tool_registry

        self.client = anthropic.AsyncAnthropic(
            api_key=config.api_key or None  # None → reads ANTHROPIC_API_KEY env
        )

        self._histories: dict[str, list[dict[str, Any]]] = {}
        self._active_runs: dict[str, bool] = {}

    # ── Tool definitions for Claude API ───────────────────────

    def _build_claude_tools(self) -> list[dict[str, Any]]:
        """Build tool definitions in Claude API format from the registries."""
        tools: list[dict[str, Any]] = []

        for name in self.tool_registry.list_tools():
            tool = self.tool_registry.get(name)
            if tool is None:
                continue
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "input_schema": _convert_params_to_json_schema(tool.parameters),
            })

        # Add load_skill (lives in SkillRegistry, not ToolRegistry)
        tools.append({
            "name": LOAD_SKILL_TOOL["name"],
            "description": LOAD_SKILL_TOOL["description"],
            "input_schema": _convert_params_to_json_schema(LOAD_SKILL_TOOL["parameters"]),
        })

        return tools

    # ── Main entry: run() ─────────────────────────────────────

    async def run(self) -> None:
        """Main loop: listen for messages from gateway, process each."""
        logger.info(
            "Agent running. Model: %s, max_iterations: %d",
            self.config.model, self.config.max_iterations,
        )

        async for message in self.gateway.receive_messages():
            text = message["text"]
            session_id = message["session_id"]

            if text == "__STOP__":
                for run_id in list(self._active_runs):
                    self._active_runs[run_id] = False
                continue

            try:
                await self.process_message(text, session_id)
            except Exception as e:
                logger.exception("Error processing message: %s", e)
                await self.gateway.stream_text(
                    f"\n\nI encountered an error: {e}. Please try again.",
                    session_id,
                )

    # ── THE CORE: process_message ─────────────────────────────

    async def process_message(self, user_message: str, session_id: str) -> None:
        """
        THE agentic loop.

        1. Signal start
        2. Build context (system prompt + message history)
        3. Loop: call Claude → stream text → execute tools → repeat
        4. Signal end
        """
        run_id = generate_run_id()
        self._active_runs[run_id] = True

        try:
            # 1. Signal start
            await self.gateway.stream_lifecycle("start", run_id, session_id)

            # 2. Build context
            system_prompt = self.context_builder.build_system_prompt(
                memory_query=user_message,
            )
            history = self._histories.get(session_id, [])
            messages = self.context_builder.build_messages(history, user_message)
            tools = self._build_claude_tools()

            # 3. THE LOOP
            iteration = 0

            while iteration < self.config.max_iterations:
                iteration += 1

                # Check cancellation
                if not self._active_runs.get(run_id, False):
                    logger.info("Run %s cancelled at iteration %d", run_id, iteration)
                    await self.gateway.stream_text("\n\n[Stopped]", session_id)
                    break

                logger.info(
                    "[%s] Iteration %d/%d",
                    run_id, iteration, self.config.max_iterations,
                )

                # Call Claude with streaming + retry
                final_message = await self._call_claude_with_retry(
                    system_prompt, messages, tools, session_id, run_id,
                )
                if final_message is None:
                    break  # Unrecoverable API error (already messaged user)

                # Append assistant response to messages
                assistant_content = []
                for block in final_message.content:
                    if hasattr(block, "model_dump"):
                        assistant_content.append(block.model_dump())
                    elif hasattr(block, "text"):
                        assistant_content.append({"type": "text", "text": block.text})
                    else:
                        assistant_content.append({"type": "text", "text": str(block)})
                messages.append({"role": "assistant", "content": assistant_content})

                # If no tool calls → done
                if final_message.stop_reason != "tool_use":
                    logger.info(
                        "[%s] Done after %d iterations (stop_reason: %s)",
                        run_id, iteration, final_message.stop_reason,
                    )
                    break

                # Execute tool calls
                tool_results = await self._process_tool_calls(
                    final_message, session_id,
                )

                # Append tool results as user message
                messages.append({"role": "user", "content": tool_results})

            else:
                # Hit max iterations
                logger.warning(
                    "[%s] Hit max iterations (%d)", run_id, self.config.max_iterations,
                )
                overflow_msg = (
                    f"\n\n[Reached maximum of {self.config.max_iterations} tool iterations. "
                    f"Stopping to prevent runaway loops. You can continue by sending another message.]"
                )
                await self.gateway.stream_text(overflow_msg, session_id)

            # Save conversation history
            self._histories[session_id] = messages

        finally:
            self._active_runs.pop(run_id, None)
            await self.gateway.stream_lifecycle("end", run_id, session_id)

    # ── Claude API calls ──────────────────────────────────────

    async def _call_claude_streaming(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        session_id: str,
        run_id: str,
    ) -> anthropic.types.Message:
        """Single Claude API call with streaming. Emits text deltas to gateway."""
        async with self.client.messages.stream(
            model=self.config.model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=self.config.max_tokens,
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    await self.gateway.stream_text(event.text, session_id)
            final_message = await stream.get_final_message()
        return final_message

    async def _call_claude_with_retry(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        session_id: str,
        run_id: str,
    ) -> Optional[anthropic.types.Message]:
        """Call Claude with retry logic for rate limits, server errors, connection errors."""
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._call_claude_streaming(
                    system, messages, tools, session_id, run_id,
                )

            except anthropic.RateLimitError:
                if attempt < MAX_RETRIES:
                    wait = min(2 ** attempt, 16)
                    logger.warning(
                        "Rate limited, retry %d/%d in %ds", attempt + 1, MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("Rate limited after %d retries", MAX_RETRIES)
                    await self.gateway.stream_text(
                        "\n\nRate limited by Claude API. Please try again in a moment.",
                        session_id,
                    )
                    return None

            except anthropic.InternalServerError:
                if attempt < 1:
                    logger.warning("Server error, retrying in 2s")
                    await asyncio.sleep(2)
                else:
                    logger.error("Claude API server error after retry")
                    await self.gateway.stream_text(
                        "\n\nClaude API server error. Please try again.",
                        session_id,
                    )
                    return None

            except anthropic.APIConnectionError as e:
                if attempt < 1:
                    logger.warning("Connection error, retrying in 1s: %s", e)
                    await asyncio.sleep(1)
                else:
                    logger.error("Connection error after retry: %s", e)
                    await self.gateway.stream_text(
                        "\n\nConnection error reaching Claude. Please try again.",
                        session_id,
                    )
                    return None

            except anthropic.APIStatusError as e:
                logger.error("Claude API error: %d %s", e.status_code, e.message)
                await self.gateway.stream_text(
                    f"\n\nAPI error: {e.message}. Please try again.",
                    session_id,
                )
                return None

        return None  # Should not reach here

    # ── Tool execution ────────────────────────────────────────

    async def _process_tool_calls(
        self,
        final_message: anthropic.types.Message,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Process all tool_use blocks from a Claude response."""
        tool_results: list[dict[str, Any]] = []

        for block in final_message.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            description = describe_tool_call(tool_name, tool_input)

            # Emit thinking step
            await self.gateway.stream_thinking(
                tool_name, description, "running", session_id,
            )

            # === Special: load_skill ===
            if tool_name == "load_skill":
                result_dict = execute_load_skill(
                    self.skill_registry,
                    tool_input.get("skill_name", ""),
                )
                success = result_dict.get("success", False)
                content = result_dict.get("output") or result_dict.get("error") or ""

                if success:
                    await self.gateway.emit_event(
                        "agent/skill:loaded",
                        {"skillName": tool_input.get("skill_name", "")},
                    )

                await self.gateway.stream_thinking(
                    tool_name, description,
                    "done" if success else "error", session_id,
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(content),
                    **({"is_error": True} if not success else {}),
                })
                continue

            # === Regular tool execution ===
            await self.gateway.emit_tool_start(tool_name, description, session_id)

            result = await self.tool_registry.execute(
                tool_name, block.id, tool_input,
            )

            content = _format_tool_result_content(result)
            summary = summarize_result(result)

            await self.gateway.emit_tool_end(
                tool_name, result.success, summary, session_id,
            )
            await self.gateway.stream_thinking(
                tool_name, description,
                "done" if result.success else "error", session_id,
            )

            # If tool produced a card, emit it
            if tool_name == "create_card" and result.success and result.output:
                try:
                    card = result.output if isinstance(result.output, dict) else json.loads(result.output)
                    await self.gateway.emit_card(card)
                except (json.JSONDecodeError, TypeError):
                    pass

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": content,
                **({"is_error": True} if not result.success else {}),
            })

        return tool_results

    # ── History management ────────────────────────────────────

    def clear_history(self, session_id: str) -> None:
        """Clear conversation history for a session."""
        self._histories.pop(session_id, None)

    def get_history(self, session_id: str) -> list[dict[str, Any]]:
        """Get conversation history for a session."""
        return self._histories.get(session_id, [])
