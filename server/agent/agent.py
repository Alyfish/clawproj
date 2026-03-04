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
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import anthropic
import httpx

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

# SDK v0.75.0 lacks OverloadedError (added later). Build a safe tuple so
# the except clause doesn't raise AttributeError at evaluation time.
_RETRIABLE_SERVER_ERRORS: tuple[type[Exception], ...] = (anthropic.InternalServerError,)
if hasattr(anthropic, "OverloadedError"):
    _RETRIABLE_SERVER_ERRORS = (anthropic.InternalServerError, anthropic.OverloadedError)


# ── Fallback response types (duck-type compatible with anthropic.types.Message) ──

@dataclass
class FallbackTextBlock:
    type: str = "text"
    text: str = ""
    def model_dump(self) -> dict:
        return {"type": self.type, "text": self.text}

@dataclass
class FallbackToolUseBlock:
    type: str = "tool_use"
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)
    def model_dump(self) -> dict:
        return {"type": self.type, "id": self.id, "name": self.name, "input": self.input}

@dataclass
class FallbackMessage:
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"


# ── Anthropic ↔ OpenAI format conversion ─────────────────────

def _to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    """Convert Anthropic message format to OpenAI format."""
    result: list[dict] = []
    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            result.append({"role": role, "content": str(content)})
            continue

        # Handle list content (Anthropic format)
        if role == "assistant":
            text_parts = []
            tool_calls = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    })
            msg_out: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
            if tool_calls:
                msg_out["tool_calls"] = tool_calls
            result.append(msg_out)

        elif role == "user":
            # Check for tool_result blocks
            has_tool_results = any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if has_tool_results:
                for block in content:
                    if block.get("type") == "tool_result":
                        result.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": block.get("content", ""),
                        })
                    elif block.get("type") == "text":
                        result.append({"role": "user", "content": block["text"]})
            else:
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif isinstance(block, str):
                        text_parts.append(block)
                result.append({"role": "user", "content": "\n".join(text_parts)})

    return result


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


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
        login_flow_manager: Any = None,
    ) -> None:
        self.config = config
        self.gateway = gateway_client
        self.context_builder = context_builder
        self.skill_registry = skill_registry
        self.tool_registry = tool_registry
        self._login_flow = login_flow_manager

        self.client = anthropic.AsyncAnthropic(
            api_key=config.api_key or None  # None → reads ANTHROPIC_API_KEY env
        )

        self._histories: dict[str, list[dict[str, Any]]] = {}
        self._active_runs: dict[str, bool] = {}
        self._task_emitted: dict[str, bool] = {}
        self._current_user_message: str = ""

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

            # Intercept login flow events (from iOS via gateway)
            if self._login_flow and message.get("login_event"):
                await self._handle_login_event(message)
                continue

            # Intercept scheduled task triggers
            if message.get("schedule_trigger"):
                await self._handle_schedule_trigger(
                    message["schedule_trigger"], session_id,
                )
                continue

            try:
                await self.process_message(text, session_id)
            except Exception as e:
                logger.exception("Error processing message: %s", e)
                await self.gateway.stream_text(
                    f"\n\nI encountered an error: {e}. Please try again.",
                    session_id,
                )

    # ── Login flow event dispatch ────────────────────────────

    async def _handle_login_event(self, message: dict) -> None:
        """Dispatch login events from iOS to LoginFlowManager."""
        event = message["login_event"]
        payload = message.get("login_payload", {})
        profile = payload.get("profile", "default")

        try:
            if event == "login/input":
                await self._login_flow.send_login_input(
                    profile=profile,
                    ref=payload["ref"],
                    text=payload["text"],
                )
            elif event == "login/click":
                await self._login_flow.click_login_element(
                    profile=profile,
                    ref=payload["ref"],
                )
            elif event == "login/done":
                await self._login_flow.stop_login_flow(profile=profile)
        except Exception as e:
            logger.error("Login event %s failed: %s", event, e)

    async def _handle_schedule_trigger(
        self, trigger: dict, session_id: str,
    ) -> None:
        """Execute a scheduled watch check triggered by the gateway scheduler."""
        job_id = trigger.get("jobId", "")
        task_description = trigger.get("taskDescription", "")
        check_instructions = trigger.get("checkInstructions", "")
        skill_name = trigger.get("skillName", "")
        previous = trigger.get("previousResult")

        # Build synthetic message for the agent to process
        parts = [
            f"[SCHEDULED WATCH CHECK — Job {job_id}]",
            f"Watch: {task_description}",
            f"Instructions: {check_instructions}",
        ]
        if skill_name:
            parts.append(f"Load skill '{skill_name}' if needed.")
        if previous:
            parts.append(
                f"Previous result (from {previous.get('executedAt', 'unknown')}):"
            )
            parts.append(json.dumps(previous.get("data", {}), indent=2))
            parts.append("Compare current data to this and note any changes.")
        parts.append(
            "\nExecute the check and provide a structured summary of findings."
        )

        synthetic_msg = "\n".join(parts)
        logger.info("Executing scheduled task %s: %s", job_id, task_description)

        try:
            await self.process_message(synthetic_msg, session_id)
            # Report success back to scheduler
            await self.gateway.emit_event("schedule/task:result", {
                "jobId": job_id,
                "status": "ok",
                "data": {},
                "summary": f"Checked: {task_description}",
            })
        except Exception as e:
            logger.error("Scheduled task %s failed: %s", job_id, e)
            await self.gateway.emit_event("schedule/task:result", {
                "jobId": job_id,
                "status": "error",
                "data": {"error": str(e)},
                "summary": f"Error: {e}",
            })

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

        self._current_user_message = user_message

        try:
            # 1. Signal start
            await self.gateway.stream_lifecycle("start", run_id, session_id)

            # Task is created lazily on first tool use (see _process_tool_calls)
            # so casual messages like "Hi" don't pollute the Tasks tab.
            task_id = run_id

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
                    final_message, session_id, task_id,
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
            # Only emit task completion if a task was actually created
            # (i.e., the agent used at least one tool during this run)
            if self._task_emitted.pop(task_id, False):
                await self.gateway.emit_task_update(task_id, "completed", step={
                    "id": uuid.uuid4().hex[:8],
                    "description": "Task completed",
                    "status": "done",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
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
    ) -> Optional[Any]:
        """Call Claude with retry logic. Falls back to OpenRouter if all retries fail."""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                return await self._call_claude_streaming(
                    system, messages, tools, session_id, run_id,
                )

            except anthropic.RateLimitError as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = min(2 ** attempt, 16)
                    logger.warning(
                        "Rate limited, retry %d/%d in %ds", attempt + 1, MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error("Rate limited after %d retries", MAX_RETRIES)

            except _RETRIABLE_SERVER_ERRORS as e:
                last_error = e
                if attempt < 1:
                    logger.warning("Server/overloaded error, retrying in 2s: %s", type(e).__name__)
                    await asyncio.sleep(2)
                else:
                    logger.error("Server/overloaded error after retry: %s", type(e).__name__)

            except anthropic.APIConnectionError as e:
                last_error = e
                if attempt < 1:
                    logger.warning("Connection error, retrying in 1s: %s", e)
                    await asyncio.sleep(1)
                else:
                    logger.error("Connection error after retry: %s", e)

            except anthropic.APIStatusError as e:
                last_error = e
                if e.status_code == 529:
                    # Overloaded — retry once (belt-and-suspenders for SDK without OverloadedError)
                    if attempt < 1:
                        logger.warning("Overloaded (529), retrying in 2s")
                        await asyncio.sleep(2)
                    else:
                        logger.error("Overloaded (529) after retry")
                else:
                    logger.error("Claude API error: %d %s", e.status_code, e.message)
                    break  # Non-retryable, fall through to OpenRouter

        # All Anthropic retries failed — try OpenRouter fallback (cascade through models)
        if self.config.openrouter_api_key and self.config.openrouter_models:
            for model_id in self.config.openrouter_models:
                logger.info("Falling back to OpenRouter (model: %s)", model_id)
                try:
                    return await self._call_openrouter_streaming(
                        system, messages, tools, session_id, run_id, model_id,
                    )
                except Exception as e:
                    logger.warning("OpenRouter model %s failed: %s", model_id, e)
                    continue

            # All models exhausted
            await self.gateway.stream_text(
                "\n\nAll fallback models are unavailable. Please try again later.",
                session_id,
            )
            return None

        # No fallback configured — report the original error
        error_msg = str(last_error) if last_error else "Unknown error"
        await self.gateway.stream_text(
            f"\n\nClaude API error: {error_msg}. Please try again.",
            session_id,
        )
        return None

    # ── OpenRouter fallback ────────────────────────────────────

    async def _call_openrouter_streaming(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        session_id: str,
        run_id: str,
        model_id: str,
    ) -> FallbackMessage:
        """Call OpenRouter via httpx. Converts Anthropic→OpenAI format, streams SSE."""
        openai_messages = _to_openai_messages(system, messages)
        openai_tools = _to_openai_tools(tools) if tools else None

        body: dict[str, Any] = {
            "model": model_id,
            "messages": openai_messages,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        if openai_tools:
            body["tools"] = openai_tools

        headers = {
            "Authorization": f"Bearer {self.config.openrouter_api_key}",
            "Content-Type": "application/json",
        }

        collected_text = ""
        collected_tool_calls: dict[int, dict] = {}

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                json=body,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    raise RuntimeError(f"OpenRouter {response.status_code}: {error_body.decode()}")

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # Stream text
                    if delta.get("content"):
                        collected_text += delta["content"]
                        await self.gateway.stream_text(delta["content"], session_id)

                    # Collect tool calls
                    for tc in delta.get("tool_calls", []):
                        idx = tc.get("index", 0)
                        if idx not in collected_tool_calls:
                            collected_tool_calls[idx] = {"id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"), "name": "", "arguments": ""}
                        if tc.get("id"):
                            collected_tool_calls[idx]["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            collected_tool_calls[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            collected_tool_calls[idx]["arguments"] += fn["arguments"]

        # Build FallbackMessage
        content: list[Any] = []
        if collected_text:
            content.append(FallbackTextBlock(text=collected_text))

        stop_reason = "end_turn"
        if collected_tool_calls:
            stop_reason = "tool_use"
            for tc in collected_tool_calls.values():
                try:
                    input_data = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except json.JSONDecodeError:
                    input_data = {}
                content.append(FallbackToolUseBlock(
                    id=tc["id"], name=tc["name"], input=input_data,
                ))

        return FallbackMessage(content=content, stop_reason=stop_reason)

    # ── Tool execution ────────────────────────────────────────

    async def _process_tool_calls(
        self,
        final_message: anthropic.types.Message,
        session_id: str,
        task_id: str = "",
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

            # Lazily create task on first tool use (so "Hi" doesn't become a task)
            if task_id and not self._task_emitted.get(task_id):
                self._task_emitted[task_id] = True
                await self.gateway.emit_task_update(task_id, "executing", step={
                    "id": uuid.uuid4().hex[:8],
                    "description": self._current_user_message[:100],
                    "status": "running",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            # Emit task step update for the iOS Tasks tab
            if task_id:
                await self.gateway.emit_task_update(task_id, "executing", step={
                    "id": uuid.uuid4().hex[:8],
                    "description": summary,
                    "status": "done" if result.success else "error",
                    "toolName": tool_name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            # If tool produced a card, emit it
            if tool_name == "create_card" and result.success and result.output:
                try:
                    card = result.output if isinstance(result.output, dict) else json.loads(result.output)
                    await self.gateway.emit_card(card)
                    if task_id:
                        await self.gateway.emit_task_update(task_id, "executing", card=card)
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

    async def shutdown(self) -> None:
        """Graceful shutdown — cancel active runs and clean up resources."""
        for run_id in list(self._active_runs):
            self._active_runs[run_id] = False

        if self._login_flow is not None:
            try:
                await self._login_flow.shutdown()
            except Exception as e:
                logger.warning("Login flow shutdown error: %s", e)
