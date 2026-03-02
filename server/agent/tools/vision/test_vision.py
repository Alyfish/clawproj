"""
Integration tests for the agentic vision pipeline.

Tests cover all 4 phases: detect → extract → verify → format.
10 offline tests (no API key) + 3 live tests (with API key).

Usage: python3 -m server.agent.tools.vision.test_vision
"""
from __future__ import annotations

import asyncio
import json
import os
import logging
import time

from server.agent.tools.vision.image_utils import (
    validate_and_preprocess, create_test_image,
    ImageValidationError, ProcessedImage,
)
from server.agent.tools.vision.schemas import (
    DETECTION_SCHEMA, EXTRACTION_SCHEMAS, VERIFICATION_SCHEMA,
    resolve_hint, get_extraction_schema,
)
from server.agent.tools.vision.card_builder import build_card, format_as_text
from server.agent.tools.vision.vision_tool import VisionTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


async def run_tests():
    print("=" * 60)
    print("Vision Pipeline Integration Tests")
    print("=" * 60)

    passed = 0
    failed = 0

    async def test(name, fn):
        nonlocal passed, failed
        try:
            await fn() if asyncio.iscoroutinefunction(fn) else fn()
            passed += 1
            print(f"  ✅ {name}")
        except Exception as e:
            failed += 1
            print(f"  ❌ {name}: {e}")

    # ─── Offline tests (no API key) ─────────────────────

    print("\n📍 Image Utils")

    async def test_create_image():
        img = create_test_image()
        assert len(img) > 100
    await test("Create test image", test_create_image)

    async def test_validate_good():
        img = create_test_image()
        result = validate_and_preprocess(img)
        assert isinstance(result, ProcessedImage)
        assert result.media_type in ("image/png", "image/jpeg")
        assert result.width > 0
    await test("Validate good image", test_validate_good)

    async def test_validate_data_uri():
        img = create_test_image()
        data_uri = f"data:image/png;base64,{img}"
        result = validate_and_preprocess(data_uri)
        assert result.width > 0
    await test("Validate data URI prefix", test_validate_data_uri)

    async def test_validate_empty():
        try:
            validate_and_preprocess("")
            assert False, "Should have raised"
        except ImageValidationError:
            pass
    await test("Reject empty input", test_validate_empty)

    async def test_validate_bad_b64():
        try:
            validate_and_preprocess("!!!not-base64!!!")
            assert False, "Should have raised"
        except ImageValidationError:
            pass
    await test("Reject invalid base64", test_validate_bad_b64)

    print("\n📍 Schemas")

    async def test_hint_resolution():
        assert resolve_hint("flight booking") == "flight_booking"
        assert resolve_hint("apartment") == "apartment_listing"
        assert resolve_hint("bet slip") == "bet_slip"
        assert resolve_hint("receipt") == "receipt"
        assert resolve_hint("") is None
        assert resolve_hint("random xyz") is None
    await test("Hint resolution", test_hint_resolution)

    async def test_schema_lookup():
        s = get_extraction_schema("flight_booking")
        assert s["name"] == "extract_flight_data"
        s = get_extraction_schema("nonexistent")
        assert s["name"] == "extract_generic_data"
        assert len(EXTRACTION_SCHEMAS) >= 5
    await test("Schema lookup + fallback", test_schema_lookup)

    print("\n📍 Card Builder")

    async def test_flight_card():
        data = {"airline": "BA", "departure_airport": "SFO",
                "arrival_airport": "LHR", "price": "$499",
                "confidence": 0.9, "uncertain_fields": ["arrival_time"]}
        card = build_card(data, "flight_booking")
        assert card["type"] == "flight"
        assert "SFO" in card["title"]
        assert "LHR" in card["title"]
        assert card["metadata"]["confidence"] == 0.9
    await test("Flight card building", test_flight_card)

    async def test_text_format():
        data = {"merchant": "Starbucks", "total": "$5.75",
                "confidence": 0.85, "uncertain_fields": []}
        text = format_as_text(data, "receipt")
        assert "Starbucks" in text
        assert "$5.75" in text
    await test("Text output formatting", test_text_format)

    async def test_low_confidence_card():
        data = {"detected_type": "unknown", "confidence": 0.3,
                "uncertain_fields": ["everything"], "fields": {"some": "data"}}
        card = build_card(data, "unknown")
        assert "low_confidence_warning" in card.get("metadata", {})
    await test("Low confidence warning in card", test_low_confidence_card)

    print("\n📍 Vision Tool Init")

    async def test_tool_init():
        tool = VisionTool()
        assert tool.name == "vision"
        assert "image_base64" in tool.parameters
        assert tool.parameters["image_base64"]["required"] is True
        assert tool.parameters["hint"]["required"] is False
        assert tool.parameters["output_format"]["required"] is False
    await test("VisionTool initialization", test_tool_init)

    # ─── Live tests (with API key) ─────────────────────

    if os.environ.get("ANTHROPIC_API_KEY"):
        print("\n📍 Live API Tests")

        async def test_live_full_pipeline():
            tool = VisionTool()
            img = create_test_image()
            result = await tool.execute(
                image_base64=img,
                hint="flight booking",
                output_format="json",
            )
            assert result.success, f"Failed: {result.error}"
            data = json.loads(result.output)
            assert data.get("detected_type") in ("flight_booking", "flight")
            assert data.get("confidence", 0) > 0.3
            print(f"    Detected: {data.get('detected_type')}")
            print(f"    Confidence: {data.get('confidence', 0):.0%}")
            print(f"    Route: {data.get('departure_airport', '?')} → {data.get('arrival_airport', '?')}")
            print(f"    Price: {data.get('price', '?')}")
        await test("Full pipeline (flight, json)", test_live_full_pipeline)

        async def test_live_card_output():
            tool = VisionTool()
            img = create_test_image()
            result = await tool.execute(
                image_base64=img,
                hint="flight",
                output_format="card",
            )
            assert result.success, f"Failed: {result.error}"
            card = json.loads(result.output)
            assert "title" in card
            assert card.get("type") in ("flight", "flight_booking")
            print(f"    Card: {card.get('title')}")
        await test("Full pipeline (flight, card)", test_live_card_output)

        async def test_live_no_hint():
            tool = VisionTool()
            img = create_test_image()
            result = await tool.execute(
                image_base64=img,
                output_format="json",
            )
            assert result.success, f"Failed: {result.error}"
            data = json.loads(result.output)
            assert "detected_type" in data
            print(f"    Detected (no hint): {data.get('detected_type')}")
            print(f"    Confidence: {data.get('confidence', 0):.0%}")
        await test("Full pipeline (no hint)", test_live_no_hint)
    else:
        print("\n📍 Live API Tests — SKIPPED (no ANTHROPIC_API_KEY)")

    # Summary
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    if failed > 0:
        print("\n⚠ Some tests failed!")
    else:
        print("\n✅ All tests passed!")
    print("\nTo run live tests:")
    print("  ANTHROPIC_API_KEY=key python3 -m server.agent.tools.vision.test_vision")


if __name__ == "__main__":
    asyncio.run(run_tests())
