"""
Agentic Vision Pipeline — ClawBot's multi-pass image extraction tool.

NOT a single API call. This is an agentic loop:

  Phase 1 — DETECT: What am I looking at?
    → Open-ended classification, description, quality assessment
    → Claude identifies content type without schema forcing
    → If hint provided, uses it for faster routing

  Phase 2 — EXTRACT: Pull structured fields
    → Select typed schema based on Phase 1 result
    → Force tool_use via tool_choice for guaranteed structured output
    → Claude populates exact fields for the detected content type

  Phase 3 — VERIFY: Are we confident enough? (conditional)
    → If confidence < 0.7 OR uncertain_fields > 2
    → Targeted follow-up: "Look again at these specific fields"
    → Merge verified values into extraction result
    → If still uncertain, flag for the agent to handle

  Phase 4 — FORMAT: Build output
    → "json" → structured dict
    → "card" → BaseCard for iOS UI (via card_builder)
    → "text" → human-readable summary

This mirrors:
- ClawBot agent.py: while stop_reason == "tool_use" → execute → loop
- Ralph ralph.sh: detect state → act → verify → commit
- OpenManus toolcall.py: think → act → observe

2-3 Claude API calls per image (detect + extract + optional verify).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import anthropic

from server.agent.tools.tool_registry import BaseTool, ToolResult
from server.agent.tools.vision.image_utils import (
    ImageValidationError,
    ProcessedImage,
    validate_and_preprocess,
)
from server.agent.tools.vision.schemas import (
    DETECTION_PROMPT,
    DETECTION_PROMPT_WITH_HINT,
    DETECTION_SCHEMA,
    EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_TEXT_MODE,
    VERIFICATION_PROMPT,
    VERIFICATION_SCHEMA,
    get_extraction_schema,
    resolve_hint,
)
from server.agent.tools.vision.card_builder import build_card, format_as_text

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────

VISION_MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 2048
VERIFY_CONFIDENCE_THRESHOLD = 0.7
VERIFY_UNCERTAIN_THRESHOLD = 2


# ── VisionTool ────────────────────────────────────────────────


class VisionTool(BaseTool):
    """
    Agentic multi-pass vision extraction tool.
    Phases: Detect → Extract → Verify (conditional) → Format.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    # ── BaseTool properties ───────────────────────────────────

    @property
    def name(self) -> str:
        return "vision"

    @property
    def description(self) -> str:
        return (
            "Extract structured data from an image using AI vision. "
            "Send a screenshot of a flight booking, apartment listing, bet slip, receipt, "
            "or any content. Returns detected_type, structured fields, confidence, "
            "and uncertain_fields. Supports output as json, card, or text."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "image_base64": {
                "type": "string",
                "required": True,
                "description": "Base64-encoded image (JPEG, PNG, or WebP). Max 5MB.",
            },
            "hint": {
                "type": "string",
                "required": False,
                "description": (
                    "What the image shows: 'flight booking', 'bet slip', 'receipt', etc."
                ),
            },
            "output_format": {
                "type": "string",
                "required": False,
                "description": "Output format: json (default), card, or text.",
            },
        }

    # ── Main execution ────────────────────────────────────────

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Orchestrate the multi-pass vision pipeline."""
        start = time.monotonic()
        image_base64: str = kwargs.get("image_base64", "")
        hint: str = kwargs.get("hint", "")
        output_format: str = kwargs.get("output_format", "json")

        try:
            # ═══ Preprocess ═══
            processed = validate_and_preprocess(image_base64)
            image_block = processed.to_api_block()

            # ═══ Phase 1: DETECT ═══
            detection = await self._phase_detect(image_block, hint)
            detected_type = detection.get("detected_type", "unknown")
            description = detection.get("description", "")
            data_richness = detection.get("data_richness", "medium")
            quality_issues = detection.get("quality_issues", [])

            logger.info(
                "Vision Phase 1: detected=%s, richness=%s, issues=%s",
                detected_type, data_richness, quality_issues,
            )

            # If hint was provided and maps to a known type, prefer it
            # (unless detection data_richness is too low to trust)
            hint_type = resolve_hint(hint)
            if hint_type and hint_type != detected_type:
                if data_richness != "low":
                    logger.info(
                        "Vision: using hint type '%s' over detected '%s'",
                        hint_type, detected_type,
                    )
                    detected_type = hint_type

            # ═══ Phase 2: EXTRACT ═══
            extraction = await self._phase_extract(
                image_block, detected_type, description, output_format,
            )
            confidence = extraction.get("confidence", 0.5)
            uncertain = extraction.get("uncertain_fields", [])

            logger.info(
                "Vision Phase 2: confidence=%.0f%%, uncertain=%s",
                confidence * 100, uncertain,
            )

            # ═══ Phase 3: VERIFY (conditional) ═══
            needs_verify = (
                confidence < VERIFY_CONFIDENCE_THRESHOLD
                or len(uncertain) > VERIFY_UNCERTAIN_THRESHOLD
            )
            if needs_verify and data_richness != "low":
                logger.info(
                    "Vision Phase 3: verifying %d uncertain fields", len(uncertain),
                )
                extraction = await self._phase_verify(
                    image_block, extraction, uncertain,
                )

            # Ensure detected_type is in the extraction
            if "detected_type" not in extraction:
                extraction["detected_type"] = detected_type

            # Add detection metadata
            extraction["_detection"] = {
                "description": description,
                "data_richness": data_richness,
                "quality_issues": quality_issues,
                "phases_run": 3 if needs_verify and data_richness != "low" else 2,
                "image_dimensions": f"{processed.width}x{processed.height}",
            }

            # ═══ Phase 4: FORMAT ═══
            if output_format == "text":
                output = format_as_text(extraction, detected_type)
            elif output_format == "card":
                card = build_card(extraction, detected_type)
                output = json.dumps(card, indent=2, default=str)
            else:
                output = json.dumps(extraction, indent=2, default=str)

            duration_ms = (time.monotonic() - start) * 1000
            logger.info("Vision pipeline complete in %.0fms", duration_ms)
            return self.success(output)

        except ImageValidationError as e:
            return self.fail(f"Image validation: {e}")
        except anthropic.APIStatusError as e:
            return self.fail(f"Claude API error ({e.status_code}): {e.message}")
        except anthropic.APIConnectionError:
            return self.fail("Cannot connect to Claude API")
        except Exception as e:
            logger.exception("Vision pipeline failed: %s", e)
            return self.fail(f"Vision error: {e}")

    # ═══════════════════════════════════════════════════════════
    # Phase 1: DETECT — What am I looking at?
    # ═══════════════════════════════════════════════════════════

    async def _phase_detect(self, image_block: dict, hint: str) -> dict:
        """
        Phase 1: Send image for open-ended classification.
        Returns: { detected_type, description, data_richness, quality_issues }
        """
        prompt = (
            DETECTION_PROMPT_WITH_HINT.format(hint=hint) if hint
            else DETECTION_PROMPT
        )

        client = self._get_client()
        response = await client.messages.create(
            model=VISION_MODEL,
            max_tokens=1024,
            tools=[DETECTION_SCHEMA],
            tool_choice={"type": "tool", "name": "report_detection"},
            messages=[{
                "role": "user",
                "content": [image_block, {"type": "text", "text": prompt}],
            }],
        )

        return self._extract_tool_input(response, "report_detection")

    # ═══════════════════════════════════════════════════════════
    # Phase 2: EXTRACT — Pull structured fields
    # ═══════════════════════════════════════════════════════════

    async def _phase_extract(
        self,
        image_block: dict,
        detected_type: str,
        description: str,
        output_format: str,
    ) -> dict:
        """
        Phase 2: Extract structured fields using the typed schema.
        Forces tool_use via tool_choice for guaranteed structured output.
        """
        schema = get_extraction_schema(detected_type)

        prompt = (
            EXTRACTION_PROMPT_TEXT_MODE.format(description=description)
            if output_format == "text"
            else EXTRACTION_PROMPT.format(
                detected_type=detected_type,
                description=description,
            )
        )

        client = self._get_client()
        response = await client.messages.create(
            model=VISION_MODEL,
            max_tokens=MAX_TOKENS,
            tools=[schema],
            tool_choice={"type": "tool", "name": schema["name"]},
            messages=[{
                "role": "user",
                "content": [image_block, {"type": "text", "text": prompt}],
            }],
        )

        return self._extract_tool_input(response, schema["name"])

    # ═══════════════════════════════════════════════════════════
    # Phase 3: VERIFY — Re-examine uncertain fields
    # ═══════════════════════════════════════════════════════════

    async def _phase_verify(
        self,
        image_block: dict,
        extraction: dict,
        uncertain_fields: list[str],
    ) -> dict:
        """
        Phase 3: Targeted re-examination of uncertain fields.
        Merges verified values back into the extraction result.
        """
        previous_values = "\n".join(
            f"  {field}: {extraction.get(field, '(not extracted)')}"
            for field in uncertain_fields
        )

        prompt = VERIFICATION_PROMPT.format(
            uncertain_fields=", ".join(uncertain_fields),
            previous_values=previous_values,
        )

        client = self._get_client()
        response = await client.messages.create(
            model=VISION_MODEL,
            max_tokens=1024,
            tools=[VERIFICATION_SCHEMA],
            tool_choice={"type": "tool", "name": "verify_fields"},
            messages=[{
                "role": "user",
                "content": [image_block, {"type": "text", "text": prompt}],
            }],
        )

        verification = self._extract_tool_input(response, "verify_fields")

        # Merge verified values
        verified = verification.get("verified_fields", {})
        still_uncertain = verification.get("still_uncertain", [])
        verify_confidence = verification.get("confidence", 0.5)

        for field, value in verified.items():
            if value and value != "unreadable":
                extraction[field] = value
                if field in extraction.get("uncertain_fields", []):
                    extraction["uncertain_fields"].remove(field)

        # Update uncertain_fields to only what's still uncertain
        extraction["uncertain_fields"] = still_uncertain

        # Boost confidence if verification helped
        old_confidence = extraction.get("confidence", 0.5)
        if verified:
            extraction["confidence"] = min(1.0, max(old_confidence, verify_confidence))

        logger.info(
            "Vision Phase 3: verified %d fields, %d still uncertain, "
            "confidence %.0f%% → %.0f%%",
            len(verified), len(still_uncertain),
            old_confidence * 100, extraction["confidence"] * 100,
        )

        return extraction

    # ═══════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════

    def _extract_tool_input(self, response: Any, expected_tool: str) -> dict:
        """Extract the tool input dict from a Claude response.

        Checks for the expected tool name first, then falls back to any
        tool_use block, then to parsing text content as JSON.
        """
        # Exact match
        for block in response.content:
            if block.type == "tool_use" and block.name == expected_tool:
                return block.input

        # Any tool_use block (shouldn't happen with tool_choice)
        for block in response.content:
            if block.type == "tool_use":
                logger.warning(
                    "Vision: expected tool '%s', got '%s'",
                    expected_tool, block.name,
                )
                return block.input

        # Text fallback (shouldn't happen with tool_choice)
        for block in response.content:
            if block.type == "text":
                try:
                    return json.loads(block.text)
                except json.JSONDecodeError:
                    return {
                        "detected_type": "unknown",
                        "text_content": block.text,
                        "confidence": 0.2,
                        "uncertain_fields": ["all"],
                    }

        return {"detected_type": "unknown", "confidence": 0.0, "uncertain_fields": ["all"]}
