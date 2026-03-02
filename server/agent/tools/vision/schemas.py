"""
Extraction schemas and prompt templates for the vision pipeline.

Each schema defines a Claude tool whose input_schema describes the fields to extract.
The agentic pipeline uses these in Phase 2 (Extract) via tool_choice forcing.

Phase 1 (Detect) uses the DETECTION_SCHEMA — open-ended, identifies content type.
Phase 2 (Extract) uses a type-specific schema — tight fields for the detected type.
Phase 3 (Verify) uses VERIFICATION_PROMPT_TEMPLATE — targeted re-check of uncertain fields.

Reference: anthropic-cookbook/tool_use/vision_with_tools.ipynb
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
# Phase 1: Detection schema (open-ended — what am I looking at?)
# ═══════════════════════════════════════════════════════════════

DETECTION_SCHEMA = {
    "name": "report_detection",
    "description": "Report what type of content the image contains and provide an initial reading.",
    "input_schema": {
        "type": "object",
        "properties": {
            "detected_type": {
                "type": "string",
                "enum": [
                    "flight_booking", "apartment_listing", "bet_slip", "receipt",
                    "document", "screenshot", "chart", "form", "photo", "menu",
                    "ticket", "invoice", "map", "unknown"
                ],
                "description": "The primary content type of the image"
            },
            "secondary_type": {
                "type": "string",
                "description": "Secondary classification if ambiguous (e.g., 'email' for a screenshot of a booking email)"
            },
            "description": {
                "type": "string",
                "description": "1-2 sentence description of what the image shows"
            },
            "visible_text_summary": {
                "type": "string",
                "description": "Summary of key text visible in the image (not full OCR, just highlights)"
            },
            "data_richness": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "How much structured data can be extracted. high=clear structured content, medium=some fields visible, low=mostly unstructured or blurry"
            },
            "quality_issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Image quality issues: 'blurry', 'partial', 'dark', 'rotated', 'small_text', 'low_resolution', 'occluded'"
            }
        },
        "required": ["detected_type", "description", "data_richness"]
    }
}

DETECTION_PROMPT = (
    "You are a visual content classifier. Examine this image and identify:\n"
    "1. What TYPE of content is this? (flight booking, apartment listing, bet slip, receipt, etc.)\n"
    "2. Briefly describe what you see.\n"
    "3. How much structured data can be extracted (high/medium/low)?\n"
    "4. Note any quality issues (blurry, partial, dark, etc.).\n\n"
    "Call the report_detection tool with your findings."
)

DETECTION_PROMPT_WITH_HINT = (
    "You are a visual content classifier. The user believes this image shows: {hint}.\n"
    "Examine the image and confirm or correct this classification:\n"
    "1. What TYPE of content is this actually?\n"
    "2. Briefly describe what you see.\n"
    "3. How much structured data can be extracted?\n"
    "4. Note any quality issues.\n\n"
    "Call the report_detection tool with your findings."
)


# ═══════════════════════════════════════════════════════════════
# Phase 2: Typed extraction schemas (per content type)
# ═══════════════════════════════════════════════════════════════

EXTRACTION_SCHEMAS: dict[str, dict] = {

    "flight_booking": {
        "name": "extract_flight_data",
        "description": "Extract all flight booking fields from the image.",
        "input_schema": {
            "type": "object",
            "properties": {
                "airline": {"type": "string", "description": "Airline name"},
                "flight_number": {"type": "string", "description": "Flight number (e.g., BA 287)"},
                "departure_airport": {"type": "string", "description": "Departure airport code (e.g., SFO)"},
                "arrival_airport": {"type": "string", "description": "Arrival airport code (e.g., LHR)"},
                "departure_date": {"type": "string", "description": "Departure date (YYYY-MM-DD)"},
                "departure_time": {"type": "string", "description": "Departure time (HH:MM)"},
                "arrival_date": {"type": "string", "description": "Arrival date (YYYY-MM-DD)"},
                "arrival_time": {"type": "string", "description": "Arrival time (HH:MM)"},
                "price": {"type": "string", "description": "Total price with currency symbol"},
                "cabin_class": {"type": "string", "description": "Economy, business, first, premium economy"},
                "confirmation_number": {"type": "string", "description": "Booking confirmation or PNR code"},
                "passengers": {"type": "string", "description": "Passenger name(s)"},
                "stops": {"type": "string", "description": "Nonstop, 1 stop, etc."},
                "duration": {"type": "string", "description": "Flight duration"},
                "confidence": {"type": "number", "description": "Overall extraction confidence 0.0–1.0"},
                "uncertain_fields": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Field names where you are not confident in the extracted value"
                }
            },
            "required": ["confidence", "uncertain_fields"]
        }
    },

    "apartment_listing": {
        "name": "extract_apartment_data",
        "description": "Extract all apartment/rental listing fields from the image.",
        "input_schema": {
            "type": "object",
            "properties": {
                "address": {"type": "string"},
                "neighborhood": {"type": "string"},
                "city": {"type": "string"},
                "rent": {"type": "string", "description": "Monthly rent with currency"},
                "deposit": {"type": "string"},
                "bedrooms": {"type": "number"},
                "bathrooms": {"type": "number"},
                "square_feet": {"type": "string"},
                "amenities": {"type": "array", "items": {"type": "string"}},
                "pet_policy": {"type": "string"},
                "parking": {"type": "string"},
                "laundry": {"type": "string"},
                "contact_name": {"type": "string"},
                "contact_phone": {"type": "string"},
                "contact_email": {"type": "string"},
                "available_date": {"type": "string"},
                "lease_terms": {"type": "string"},
                "listing_source": {"type": "string", "description": "Platform: Zillow, Apartments.com, etc."},
                "confidence": {"type": "number"},
                "uncertain_fields": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["confidence", "uncertain_fields"]
        }
    },

    "bet_slip": {
        "name": "extract_bet_data",
        "description": "Extract all sports bet slip fields from the image.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sportsbook": {"type": "string", "description": "DraftKings, FanDuel, BetMGM, etc."},
                "sport": {"type": "string"},
                "league": {"type": "string", "description": "NFL, NBA, MLB, NHL, etc."},
                "matchup": {"type": "string", "description": "Teams or event"},
                "bet_type": {"type": "string", "description": "moneyline, spread, over/under, parlay, prop, etc."},
                "selection": {"type": "string", "description": "What was selected (team, over, player prop, etc.)"},
                "line": {"type": "string", "description": "The line (-3.5, O/U 48.5, etc.)"},
                "odds": {"type": "string", "description": "American (-110), decimal (1.91), or fractional (10/11)"},
                "stake": {"type": "string", "description": "Amount wagered with currency"},
                "potential_payout": {"type": "string"},
                "event_date": {"type": "string"},
                "bet_status": {"type": "string", "description": "pending, won, lost, void, cashout"},
                "bet_id": {"type": "string", "description": "Bet slip ID or reference"},
                "is_parlay": {"type": "boolean"},
                "parlay_legs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "matchup": {"type": "string"},
                            "selection": {"type": "string"},
                            "odds": {"type": "string"}
                        }
                    },
                    "description": "Individual legs if this is a parlay"
                },
                "confidence": {"type": "number"},
                "uncertain_fields": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["confidence", "uncertain_fields"]
        }
    },

    "receipt": {
        "name": "extract_receipt_data",
        "description": "Extract all receipt/invoice fields from the image.",
        "input_schema": {
            "type": "object",
            "properties": {
                "merchant": {"type": "string"},
                "merchant_address": {"type": "string"},
                "date": {"type": "string"},
                "time": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "string"},
                            "total_price": {"type": "string"}
                        }
                    }
                },
                "subtotal": {"type": "string"},
                "tax": {"type": "string"},
                "tip": {"type": "string"},
                "total": {"type": "string"},
                "payment_method": {"type": "string"},
                "card_last_four": {"type": "string"},
                "transaction_id": {"type": "string"},
                "confidence": {"type": "number"},
                "uncertain_fields": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["confidence", "uncertain_fields"]
        }
    },

    # Generic fallback — used when type is unknown or uncommon
    "generic": {
        "name": "extract_generic_data",
        "description": "Extract all structured data from the image, regardless of content type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "detected_type": {"type": "string"},
                "title": {"type": "string", "description": "Brief title for the content"},
                "fields": {
                    "type": "object",
                    "description": "All extracted key-value data"
                },
                "text_content": {"type": "string", "description": "All visible text"},
                "numbers": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Important numbers found (prices, dates, IDs, quantities)"
                },
                "urls_or_contacts": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Any URLs, emails, phone numbers found"
                },
                "confidence": {"type": "number"},
                "uncertain_fields": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["detected_type", "confidence", "uncertain_fields"]
        }
    }
}

# Extraction prompts (Phase 2)
EXTRACTION_PROMPT = (
    "You are a precise data extraction specialist. This image has been identified as: {detected_type}.\n"
    "Previous analysis: {description}\n\n"
    "Now extract ALL structured fields by calling the provided tool.\n"
    "Rules:\n"
    "- Be exact with numbers, dates, times, currencies, codes.\n"
    "- If a field is partially visible, extract what you can and add the field name to uncertain_fields.\n"
    "- If a field is completely unreadable, omit it entirely and add to uncertain_fields.\n"
    "- Set confidence between 0.0 (guessing) and 1.0 (perfectly clear).\n"
    "- Confidence below 0.5 = poor image quality or wrong content type."
)

EXTRACTION_PROMPT_TEXT_MODE = (
    "You are an OCR specialist. Extract ALL visible text from this image.\n"
    "Previous analysis: {description}\n\n"
    "Focus on capturing every readable word, number, and symbol.\n"
    "Maintain the visual layout structure as much as possible.\n"
    "Call the provided tool with your findings."
)


# ═══════════════════════════════════════════════════════════════
# Phase 3: Verification prompt template
# ═══════════════════════════════════════════════════════════════

VERIFICATION_PROMPT = (
    "You previously extracted data from this image but were uncertain about these fields: {uncertain_fields}.\n"
    "Previous extraction gave these values:\n{previous_values}\n\n"
    "Look at the image again very carefully. Focus ONLY on the uncertain fields.\n"
    "For each field, either:\n"
    "- Confirm the value if you're now more confident\n"
    "- Correct it if you see a different value\n"
    "- Mark it as 'unreadable' if you truly cannot determine it\n\n"
    "Call the tool with your refined extraction. Only include the fields you're verifying."
)

VERIFICATION_SCHEMA = {
    "name": "verify_fields",
    "description": "Provide corrected or confirmed values for previously uncertain fields.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verified_fields": {
                "type": "object",
                "description": "Field name → corrected/confirmed value"
            },
            "still_uncertain": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Fields that remain unreadable even after re-examination"
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in the verified fields 0.0–1.0"
            }
        },
        "required": ["verified_fields", "still_uncertain", "confidence"]
    }
}


# ═══════════════════════════════════════════════════════════════
# Hint → schema routing
# ═══════════════════════════════════════════════════════════════

HINT_TO_TYPE: dict[str, str] = {
    "flight": "flight_booking", "flight_booking": "flight_booking",
    "flight booking": "flight_booking", "flights": "flight_booking",
    "booking": "flight_booking", "airline": "flight_booking",
    "apartment": "apartment_listing", "apartment_listing": "apartment_listing",
    "apartment listing": "apartment_listing", "rental": "apartment_listing",
    "listing": "apartment_listing", "rent": "apartment_listing",
    "bet": "bet_slip", "bet_slip": "bet_slip", "bet slip": "bet_slip",
    "sports bet": "bet_slip", "wager": "bet_slip", "parlay": "bet_slip",
    "receipt": "receipt", "invoice": "receipt", "bill": "receipt",
}

def resolve_hint(hint: str) -> str | None:
    """Map a user hint to a content type. Returns None if no match."""
    if not hint:
        return None
    return HINT_TO_TYPE.get(hint.lower().strip())

def get_extraction_schema(content_type: str) -> dict:
    """Get the extraction schema for a content type. Falls back to generic."""
    return EXTRACTION_SCHEMAS.get(content_type, EXTRACTION_SCHEMAS["generic"])
