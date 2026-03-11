"""
ClawBot Context Builder

Assembles the full LLM context (system prompt + message history) for each
agentic loop turn. This is the equivalent of OpenClaw's context assembly phase.

System prompt order (intentional — safety rules first):
  1. SOUL.md (identity, principles, safety rules)
  2. Available Skills (summaries for progressive disclosure)
  3. Available Tools (base tool descriptions)
  4. Current Context (date/time, timezone)
  5. Relevant Memory (if memory system exists)

Message history pipeline (per turn):
  1. Truncate oversized tool results (head-only)
  2. Micro-compact old tool results into placeholders
  3. Inject skill content (if load_skill was called)
  4. Append new user message
  5. Compact full history if over token threshold

Patterns adopted from shareAI-lab/claw0 (MIT) and
shareAI-lab/learn-claude-code (MIT).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ============================================================
# PROTOCOLS (for optional dependencies)
# ============================================================


@runtime_checkable
class SkillRegistryProtocol(Protocol):
    """Minimal interface for the skill registry."""

    def get_summaries(self) -> str: ...
    def get_skill_content(self, name: str) -> str | None: ...


@runtime_checkable
class MemorySystemProtocol(Protocol):
    """Minimal interface for the memory system (Chunk 16)."""

    def search(self, query: str, limit: int = 5) -> list[dict]: ...


# ============================================================
# TOOL DESCRIPTION FORMATTER
# ============================================================


def format_tool_descriptions(tools: list[dict[str, Any]]) -> str:
    """
    Format a list of tool definitions into a readable section
    for the system prompt.

    Each tool dict should have: name, description, parameters (dict of ParameterDef).

    Example output:
        - http_request: Make HTTP requests to any API endpoint.
          Params: method (string, required), url (string, required), headers (object), body (object)
        - browser: Automate browser interactions.
          Params: action (string, required), url (string), ...

    Args:
        tools: List of tool definition dicts matching ToolDefinition shape.

    Returns:
        Formatted string, or empty string if no tools.
    """
    if not tools:
        return "No tools available."

    lines = []
    for tool in tools:
        name = tool.get("name", "unnamed")
        desc = tool.get("description", "")
        params = tool.get("parameters", {})

        # Format parameters
        param_parts = []
        for pname, pdef in params.items():
            ptype = pdef.get("type", "any") if isinstance(pdef, dict) else "any"
            required = pdef.get("required", False) if isinstance(pdef, dict) else False
            suffix = ", required" if required else ""
            param_parts.append(f"{pname} ({ptype}{suffix})")

        param_str = ", ".join(param_parts) if param_parts else "none"
        lines.append(f"- {name}: {desc}\n  Params: {param_str}")

    return "\n".join(lines)


# ============================================================
# TOOL ORDERING
# ============================================================

# Priority map for tool ordering in the system prompt.
# Claude shows preference for tools listed earlier in the prompt.
# Lower number = listed first.
_TOOL_PRIORITY: dict[str, int] = {
    # Primary (bash-first)
    "bash_execute": 0,
    # Structured tools (specific capabilities)
    "browser": 10,
    "create_card": 11,
    "request_approval": 12,
    "vision": 13,
    "login_flow": 14,
    "schedule": 15,
    "profile_manager": 16,
    # Legacy tools (fallbacks — listed last)
    "web_search": 90,
    "http_request": 91,
    "file_io": 92,
    "code_execution": 93,
    "save_memory": 94,
    "search_memory": 95,
    "load_skill": 96,  # deprecated — agent reads skills via bash
}


def _prioritize_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder tools for system prompt: bash_execute first, legacy last.

    Tools not in the priority map get a default priority of 50
    (between structured and legacy tools).
    """
    def sort_key(t: dict[str, Any]) -> int:
        return _TOOL_PRIORITY.get(t.get("name", ""), 50)
    return sorted(tools, key=sort_key)


# ============================================================
# CONSTANTS
# ============================================================

# Default token threshold for context compaction.
# Claude's context window is 200k but we leave headroom for the response.
DEFAULT_MAX_TOKENS = 120_000

# Number of recent messages to always keep when compacting.
DEFAULT_KEEP_RECENT = 15

# Max characters for SOUL.md — prevents accidentally huge files
# from consuming the context budget. (Pattern from claw0)
MAX_SOUL_CHARS = 20_000

# Max characters for a single tool result before head-only truncation.
# (Pattern from claw0: stage 1 overflow recovery)
MAX_TOOL_RESULT_CHARS = 50_000

# Number of recent tool results to keep intact during micro-compact.
# (Pattern from learn-claude-code)
MICRO_COMPACT_KEEP_RECENT = 3


# ============================================================
# CONTEXT BUILDER
# ============================================================


class ContextBuilder:
    """
    Assembles the full context for each agentic loop LLM call.

    Usage:
        builder = ContextBuilder(
            soul_path="SOUL.md",
            skill_registry=registry,
            tools=base_tools,
        )

        system_prompt = builder.build_system_prompt()
        messages = builder.build_messages(
            session_history=conversation_so_far,
            user_message="Find flights to London",
        )

        # Send to Claude:
        response = client.messages.create(
            system=system_prompt,
            messages=messages,
        )
    """

    def __init__(
        self,
        soul_path: str = "SOUL.md",
        skill_registry: Optional[SkillRegistryProtocol] = None,
        memory_system: Optional[MemorySystemProtocol] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        keep_recent: int = DEFAULT_KEEP_RECENT,
        user_timezone: Optional[str] = None,
        workspace_path: Optional[str] = None,
    ):
        self._soul_path = Path(soul_path)
        self._skill_registry = skill_registry
        self._memory_system = memory_system
        self._tools = tools or []
        self._max_tokens = max_tokens
        self._keep_recent = keep_recent
        self._user_timezone = user_timezone
        self._workspace_path = workspace_path

        # Cache SOUL.md content (it doesn't change at runtime)
        self._soul_content = self._load_soul()

    # --------------------------------------------------------
    # SOUL.MD LOADING
    # --------------------------------------------------------

    def _load_soul(self) -> str:
        """Load and cache the SOUL.md file. Caps at MAX_SOUL_CHARS."""
        if not self._soul_path.exists():
            logger.warning("SOUL.md not found at %s, using fallback", self._soul_path)
            return self._fallback_soul()

        try:
            content = self._soul_path.read_text(encoding="utf-8").strip()
            if len(content) > MAX_SOUL_CHARS:
                logger.warning(
                    "SOUL.md is %d chars, truncating to %d",
                    len(content),
                    MAX_SOUL_CHARS,
                )
                content = content[:MAX_SOUL_CHARS] + "\n\n[... SOUL.md truncated ...]"
            logger.info("Loaded SOUL.md (%d chars)", len(content))
            return content
        except OSError as e:
            logger.warning("Failed to read SOUL.md: %s", e)
            return self._fallback_soul()

    @staticmethod
    def _fallback_soul() -> str:
        """Minimal fallback if SOUL.md is missing."""
        return (
            "You are ClawBot, a personal AI agent. Be helpful, concise, "
            "and action-oriented. Always request approval before payments, "
            "submissions, deletions, or sharing personal info."
        )

    # --------------------------------------------------------
    # SYSTEM PROMPT ASSEMBLY
    # --------------------------------------------------------

    def build_system_prompt(
        self,
        memory_query: Optional[str] = None,
        mode: Literal["full", "minimal"] = "full",
    ) -> str:
        """
        Build the complete system prompt.

        Concatenation order (intentional — safety first):
          1. SOUL.md              (always)
          2. Available Skills      (full mode only)
          3. Available Tools       (always)
          4. Current Context       (always)
          5. Relevant Memory       (full mode only, when query provided)

        Args:
            memory_query: Optional query to search memory for relevant context.
                          If None and memory system exists, no memory is injected.
            mode: "full" includes all sections. "minimal" skips skills and memory
                  (useful for heartbeat/cron runs that need cheap context).

        Returns:
            Full system prompt string.
        """
        sections: list[str] = []

        # 1. SOUL.md — identity, principles, safety rules
        sections.append(self._soul_content)

        # 2. Skill index pointer (full mode only)
        if mode == "full" and self._workspace_path:
            ws = self._workspace_path
            skill_hint = (
                "<skills_index>\n"
                f"Your domain skills are listed in {ws}/skills/INDEX.md. "
                f"When a user's request matches a domain, read the skill with: "
                f"cat {ws}/skills/{{name}}/SKILL.md — then follow its instructions.\n"
                "</skills_index>"
            )
            sections.append(skill_hint)

        # 3. Available Tools (ordered: bash_execute first, legacy last)
        if self._tools:
            ordered = _prioritize_tools(self._tools)
            tool_section = (
                "<available_tools>\n"
                + format_tool_descriptions(ordered)
                + "\n</available_tools>"
            )
            sections.append(tool_section)

        # 4. Current Context
        sections.append(self._build_current_context())

        # 5. Relevant Memory (full mode only)
        if mode == "full" and memory_query and self._memory_system is not None:
            memory_section = self.inject_memory(memory_query)
            if memory_section:
                sections.append(memory_section)

        return "\n\n".join(sections)

    def _build_current_context(self) -> str:
        """Build the current context section (date, time, timezone)."""
        now = datetime.now(timezone.utc)
        parts = [
            "<current_context>",
            f"Current date: {now.strftime('%A, %B %d, %Y')}",
            f"Current time (UTC): {now.strftime('%H:%M')}",
        ]

        if self._user_timezone:
            parts.append(f"User timezone: {self._user_timezone}")

        parts.append("</current_context>")
        return "\n".join(parts)

    # --------------------------------------------------------
    # MEMORY INJECTION
    # --------------------------------------------------------

    def inject_memory(self, query: str, limit: int = 5) -> str:
        """
        Search memory for relevant entries and format as a context section.

        Args:
            query: Search query (typically derived from the user's message).
            limit: Max number of memory entries to include.

        Returns:
            Formatted memory section string, or empty string if no results.
        """
        if self._memory_system is None:
            return ""

        try:
            results = self._memory_system.search(query, limit=limit)
        except Exception as e:
            logger.warning("Memory search failed: %s", e)
            return ""

        if not results:
            return ""

        lines = ["<relevant_memory>"]
        for r in results:
            key = r.get("key", "unknown")
            content = r.get("content", "")
            score = r.get("relevance_score", 0)
            # Only include reasonably relevant results
            if score < 0.1:
                continue
            lines.append(f"### {key}")
            lines.append(content.strip())
            lines.append("")
        lines.append("</relevant_memory>")

        # If all entries were below threshold, return empty
        if len(lines) <= 2:
            return ""

        return "\n".join(lines)

    # --------------------------------------------------------
    # MESSAGE HISTORY ASSEMBLY
    # --------------------------------------------------------

    def build_messages(
        self,
        session_history: list[dict[str, Any]],
        user_message: str,
        injected_skill: Optional[str] = None,
        injected_skill_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Build the message array for the LLM call.

        Pipeline:
          1. Truncate oversized tool results (prevents single results from blowing context)
          2. Micro-compact old tool results (collapse to placeholders)
          3. Inject skill content (if load_skill was called this turn)
          4. Append new user message
          5. Compact full history if over token threshold

        Args:
            session_history: Previous messages [{role, content}, ...].
            user_message: The new user message for this turn.
            injected_skill: Full skill content to inject (from load_skill).
            injected_skill_name: Name of the injected skill.

        Returns:
            List of message dicts ready for the Claude API.
        """
        messages: list[dict[str, Any]] = []

        # Start with session history
        messages.extend(session_history)

        # Stage 1: Truncate oversized tool results (claw0 pattern)
        self.truncate_tool_results(messages)

        # Stage 2: Micro-compact old tool results (learn-claude-code pattern)
        self.micro_compact(messages)

        # Stage 2.5: Offload remaining large tool results to files
        self._offload_large_tool_results(messages)

        # Inject skill content if a skill was loaded this turn.
        # Injected as a user message with system context marker
        # so the LLM sees the skill instructions before the user's request.
        if injected_skill:
            name = injected_skill_name or "unknown"
            messages.append({
                "role": "user",
                "content": (
                    f"[System: Skill '{name}' loaded. Follow these instructions.]\n\n"
                    f"{injected_skill}"
                ),
            })
            # Claude expects alternating user/assistant, so add a brief ack
            messages.append({
                "role": "assistant",
                "content": (
                    f"Understood. I've loaded the {name} skill and will follow "
                    "its instructions for this task."
                ),
            })

        # Append the new user message
        messages.append({
            "role": "user",
            "content": user_message,
        })

        # Stage 3: Compact if history is too long
        total_tokens = self._estimate_tokens_messages(messages)
        if total_tokens > self._max_tokens:
            logger.info(
                "Message history exceeds %d tokens (~%d), compacting",
                self._max_tokens,
                total_tokens,
            )
            messages = self.compact_history(messages)

        return messages

    # --------------------------------------------------------
    # TOOL RESULT TRUNCATION (from claw0)
    # --------------------------------------------------------

    @staticmethod
    def truncate_tool_results(
        messages: list[dict[str, Any]],
        max_chars: int = MAX_TOOL_RESULT_CHARS,
    ) -> None:
        """
        Truncate oversized tool_result content strings in-place.

        Head-only truncation: keeps the first max_chars characters.
        Prevents a single enormous tool result from blowing context.

        Args:
            messages: Message list (modified in place).
            max_chars: Max characters per tool result before truncation.
        """
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") != "tool_result":
                    continue
                text = part.get("content", "")
                if isinstance(text, str) and len(text) > max_chars:
                    original_len = len(text)
                    part["content"] = (
                        text[:max_chars]
                        + f"\n\n[... truncated ({original_len} chars total, "
                        f"showing first {max_chars}) ...]"
                    )

    # --------------------------------------------------------
    # MICRO-COMPACT (from learn-claude-code)
    # --------------------------------------------------------

    @staticmethod
    def micro_compact(
        messages: list[dict[str, Any]],
        keep_recent: int = MICRO_COMPACT_KEEP_RECENT,
    ) -> None:
        """
        Collapse old tool_result content into short placeholders, in-place.

        Keeps the last `keep_recent` tool results intact. Older ones
        are replaced with '[Previous: used {tool_name}]'. This runs
        every turn and is very cheap (no LLM calls).

        Args:
            messages: Message list (modified in place).
            keep_recent: Number of recent tool results to keep intact.
        """
        # Step 1: Build a map of tool_use_id → tool_name from assistant messages
        tool_name_map: dict[str, str] = {}
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_name_map[block.get("id", "")] = block.get("name", "unknown")

        # Step 2: Collect all tool_result entries with their locations
        tool_results: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    tool_results.append(part)

        if len(tool_results) <= keep_recent:
            return

        # Step 3: Collapse old results (all except the last keep_recent)
        to_collapse = tool_results[:-keep_recent]
        for result in to_collapse:
            text = result.get("content", "")
            if isinstance(text, str) and len(text) > 100:
                tool_id = result.get("tool_use_id", "")
                tool_name = tool_name_map.get(tool_id, "unknown")
                result["content"] = f"[Previous: used {tool_name}]"

    # --------------------------------------------------------
    # TOOL RESULT OFFLOADING
    # --------------------------------------------------------

    TOOL_RESULT_OFFLOAD_THRESHOLD = 5_000  # 5KB

    def _offload_large_tool_results(self, messages: list[dict]) -> None:
        """Save tool results >5KB to files and replace inline. In-place."""
        if not self._workspace_path:
            return
        data_dir = Path(self._workspace_path) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "tool_result":
                    continue
                text = part.get("content", "")
                if not isinstance(text, str) or len(text) <= self.TOOL_RESULT_OFFLOAD_THRESHOLD:
                    continue
                content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
                filepath = data_dir / f"tool-result-{content_hash}.json"
                try:
                    filepath.write_text(text, encoding="utf-8")
                    part["content"] = (
                        f"[Output saved to {filepath} ({len(text)} chars) "
                        f"— use bash to read specific parts]"
                    )
                except OSError as e:
                    logger.warning("Failed to offload tool result: %s", e)

    # --------------------------------------------------------
    # CONTEXT COMPACTION
    # --------------------------------------------------------

    def compact_history(
        self,
        messages: list[dict[str, Any]],
        max_tokens: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Compact message history when it exceeds the token threshold.

        Strategy:
          1. Keep the last N messages (configurable, default 15)
          2. Save full conversation to a log file (best-effort)
          3. Replace older messages with a heuristic summary
          4. Include log file reference for recall

        Args:
            messages: Full message history.
            max_tokens: Override the default max_tokens threshold.
            session_id: Optional session ID (unused — timestamps used for log names).

        Returns:
            Compacted message list.
        """
        threshold = max_tokens or self._max_tokens

        # If within limits, return as-is
        if self._estimate_tokens_messages(messages) <= threshold:
            return messages

        keep_count = self._keep_recent
        if len(messages) <= keep_count:
            # Can't compact further — already at minimum
            return messages

        older = messages[:-keep_count]
        recent = messages[-keep_count:]

        # Save full conversation to log file (best-effort)
        log_ref = ""
        if self._workspace_path:
            log_ref = self._save_compaction_log(older + recent)

        # Build summary with file reference and heuristic
        summary_text = self._generate_compaction_summary(older, recent)
        if log_ref:
            summary_text += (
                f"\n\n[Full conversation history saved to {log_ref}]\n"
                f"To recall details: grep -n 'keyword' {log_ref}"
            )

        summary_message = {
            "role": "user",
            "content": summary_text,
        }

        # Ensure alternating roles: summary is "user", so next must be "assistant"
        # If recent starts with "user", we need an assistant ack between
        compacted = [summary_message]
        if recent and recent[0].get("role") == "user":
            compacted.append({
                "role": "assistant",
                "content": "Understood, I have the previous context.",
            })
        compacted.extend(recent)

        logger.info(
            "Compacted %d messages -> %d (removed %d older messages)",
            len(messages),
            len(compacted),
            len(older),
        )

        return compacted

    def _save_compaction_log(self, messages: list[dict]) -> str:
        """Save full conversation to a timestamped markdown log file.

        Returns reference string for the summary, or empty on failure.
        """
        logs_dir = Path(self._workspace_path) / "logs"  # type: ignore[arg-type]
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        filepath = logs_dir / f"session-{timestamp}.md"
        try:
            lines = [f"# Conversation Log — {timestamp}\n"]
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if isinstance(content, list):
                    text_parts: list[str] = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif block.get("type") == "tool_use":
                                text_parts.append(f"[tool: {block.get('name')}]")
                            elif block.get("type") == "tool_result":
                                text_parts.append(
                                    f"[tool_result: {str(block.get('content', ''))[:200]}]"
                                )
                    content = "\n".join(text_parts)
                lines.append(f"## {role}\n{content}\n")
            filepath.write_text("\n".join(lines), encoding="utf-8")
            return str(filepath)
        except OSError as e:
            logger.warning("Failed to save compaction log: %s", e)
            return ""

    def _generate_compaction_summary(
        self, older: list[dict], recent: list[dict]
    ) -> str:
        """Generate a heuristic summary of compacted messages."""
        last_user = ""
        last_assistant = ""
        workspace_paths: list[str] = []

        for msg in reversed(older):
            content_str = self._content_to_text(msg.get("content", ""))
            if not last_user and msg.get("role") == "user":
                last_user = content_str[:300]
            if not last_assistant and msg.get("role") == "assistant":
                last_assistant = content_str[:300]
            # Collect /workspace/ paths mentioned
            for word in content_str.split():
                if "/workspace/" in word or (
                    self._workspace_path and self._workspace_path in word
                ):
                    cleaned = word.strip("[](),\"'")
                    if cleaned not in workspace_paths:
                        workspace_paths.append(cleaned)

        parts = ["Summary of earlier conversation:"]
        if last_user:
            parts.append(f"- User asked: {last_user}")
        if last_assistant:
            parts.append(f"- Assistant responded: {last_assistant}")
        if workspace_paths:
            parts.append(f"- Files referenced: {', '.join(workspace_paths[:10])}")
        return "\n".join(parts)

    @staticmethod
    def _content_to_text(content: Any) -> str:
        """Extract plain text from message content (str or list)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
            return "\n".join(texts)
        return str(content)

    @staticmethod
    def _summarize_content(content: Any) -> str:
        """
        Summarize a message's content for the compaction summary.

        Handles:
        - str: truncate to 200 chars
        - list (multi-part): tool-aware formatting
        """
        if isinstance(content, str):
            truncated = content[:200] + "..." if len(content) > 200 else content
            return truncated.replace("\n", " ")

        if isinstance(content, list):
            parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "tool_use":
                    name = block.get("name", "unknown")
                    inp = json.dumps(block.get("input", {}), ensure_ascii=False)
                    inp_preview = inp[:100] + "..." if len(inp) > 100 else inp
                    parts.append(f"[tool: {name}({inp_preview})]")
                elif block_type == "tool_result":
                    tool_id = block.get("tool_use_id", "")
                    parts.append(f"[tool_result: {tool_id[:8]}]")
                elif block_type == "text":
                    text = block.get("text", "")
                    truncated = text[:200] + "..." if len(text) > 200 else text
                    parts.append(truncated.replace("\n", " "))
                else:
                    parts.append(f"[{block_type}]")
            return " | ".join(parts) if parts else "(empty)"

        return str(content)[:200]

    # --------------------------------------------------------
    # TOKEN ESTIMATION
    # --------------------------------------------------------

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Estimate token count from text.

        Heuristic: ~4 characters per token for English text.
        Good enough for context window management.
        Not accurate for billing — use the actual tokenizer for that.
        """
        return len(text) // 4

    def _estimate_tokens_messages(self, messages: list[dict[str, Any]]) -> int:
        """Estimate total tokens across all messages."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.estimate_tokens(content)
            elif isinstance(content, list):
                # Handle multi-part content (text, tool_use, tool_result, images)
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        total += self.estimate_tokens(part["text"])
                    elif isinstance(part, dict) and part.get("type") == "tool_result":
                        result_content = part.get("content", "")
                        if isinstance(result_content, str):
                            total += self.estimate_tokens(result_content)
                        else:
                            total += 100
                    elif isinstance(part, dict) and part.get("type") == "tool_use":
                        inp = json.dumps(part.get("input", {}), ensure_ascii=False)
                        total += self.estimate_tokens(inp) + 20  # name + overhead
                    elif isinstance(part, dict):
                        # Images, etc — rough estimate
                        total += 100
        return total

    # --------------------------------------------------------
    # CONFIGURATION
    # --------------------------------------------------------

    def set_user_timezone(self, tz: str) -> None:
        """Update the user's timezone for context injection."""
        self._user_timezone = tz

    def set_tools(self, tools: list[dict[str, Any]]) -> None:
        """Update the available tools list."""
        self._tools = tools

    def reload_soul(self) -> None:
        """Reload SOUL.md from disk (if it was edited)."""
        self._soul_content = self._load_soul()
