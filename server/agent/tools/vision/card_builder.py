"""
Card builder: transforms vision extraction results into ClawBot cards.

When output_format="card", the vision pipeline calls build_card() to create
a structured card dict matching shared/types/cards.ts that the agent emits
via create_card tool → gateway → iOS UI.

Card type mapping (extraction type → card type):
  flight_booking    → FlightCard   (type: "flight")
  apartment_listing → HouseCard    (type: "house")
  bet_slip          → PickCard     (type: "pick")
  receipt           → BaseCard     (type: "receipt")
  *                 → BaseCard     (type: detected_type)
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Keys that are extraction metadata, not display data
_META_KEYS = frozenset({
    "confidence", "uncertain_fields", "detected_type", "fields",
})

# Currency symbols → ISO codes
_CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY",
    "₹": "INR", "A$": "AUD", "C$": "CAD",
}


def build_card(extracted: dict[str, Any], content_type: str) -> dict[str, Any]:
    """Build a card dict from extracted vision data.

    Args:
        extracted: Dict from the vision extraction schema.
        content_type: Detected content type (e.g. "flight_booking").

    Returns:
        Card dict matching shared/types/cards.ts (BaseCard + type-specific fields).
    """
    confidence = extracted.get("confidence", 0)
    uncertain = extracted.get("uncertain_fields", [])

    builders = {
        "flight_booking": _build_flight_card,
        "apartment_listing": _build_house_card,
        "bet_slip": _build_pick_card,
        "receipt": _build_receipt_card,
    }

    builder = builders.get(content_type, _build_generic_card)
    card = builder(extracted)

    # Stamp BaseCard required fields
    card.setdefault("id", uuid.uuid4().hex[:12])
    card.setdefault("metadata", {})
    card["source"] = "vision_extraction"
    card["createdAt"] = datetime.now(timezone.utc).isoformat()

    # Store extraction provenance in metadata
    card["metadata"]["confidence"] = confidence
    if uncertain:
        card["metadata"]["uncertain_fields"] = uncertain
    if confidence < 0.7:
        card["metadata"]["low_confidence_warning"] = (
            f"Some fields may be inaccurate (confidence: {confidence:.0%}). "
            f"Uncertain: {', '.join(uncertain) if uncertain else 'general'}."
        )

    return card


# ── Type-specific builders ───────────────────────────────────


def _build_flight_card(extracted: dict[str, Any]) -> dict[str, Any]:
    """Map extraction to FlightCard (shared/types/cards.ts)."""
    dep = extracted.get("departure_airport", "???")
    arr = extracted.get("arrival_airport", "???")
    airline = extracted.get("airline", "Unknown")
    price = _parse_price(extracted.get("price", ""))

    title_parts = [airline, f"{dep} → {arr}"]
    if price["amount"]:
        title_parts.append(f"${price['amount']:.0f}" if price["currency"] == "USD"
                           else f"{price['amount']:.0f} {price['currency']}")

    return {
        "type": "flight",
        "title": " · ".join(p for p in title_parts if p),
        "subtitle": _compact(
            extracted.get("departure_date", ""),
            extracted.get("cabin_class", ""),
        ),
        "airline": airline,
        "route": {"from": dep, "to": arr},
        "departure": extracted.get("departure_date", ""),
        "arrival": extracted.get("arrival_date", ""),
        "duration": extracted.get("duration", "—"),
        "layovers": extracted.get("layovers", 0),
        "price": price,
        "baggage": extracted.get("baggage", "Unknown"),
        "refundPolicy": extracted.get("refund_policy", "Unknown"),
        "ranking": {"label": "Extracted", "reason": "From screenshot"},
        "metadata": _extraction_metadata(extracted),
    }


def _build_house_card(extracted: dict[str, Any]) -> dict[str, Any]:
    """Map extraction to HouseCard (type: 'house', not 'apartment')."""
    address = extracted.get("address", "Apartment Listing")
    rent = _parse_price(extracted.get("rent", ""))
    bedrooms = extracted.get("bedrooms", 0)
    bathrooms = extracted.get("bathrooms", "?")

    return {
        "type": "house",
        "title": address,
        "subtitle": _compact(
            f"${rent['amount']:.0f}/mo" if rent["amount"] else "",
            f"{bedrooms}bd/{bathrooms}ba",
        ),
        "address": address,
        "rent": {
            "amount": rent["amount"],
            "currency": rent["currency"],
            "period": "month",
        },
        "bedrooms": bedrooms if isinstance(bedrooms, int) else 0,
        "area": extracted.get("area", extracted.get("square_footage", "—")),
        "commute": {
            "destination": extracted.get("commute_destination", "—"),
            "time": extracted.get("commute_time", "—"),
            "mode": extracted.get("commute_mode", "—"),
        },
        "leaseTerms": extracted.get("lease_terms", "—"),
        "moveInDate": extracted.get("move_in_date", "—"),
        "requiredDocs": extracted.get("required_docs", []),
        "redFlags": extracted.get("red_flags", []),
        "source": "vision_extraction",
        "listingUrl": extracted.get("listing_url", ""),
        "metadata": _extraction_metadata(extracted),
    }


def _build_pick_card(extracted: dict[str, Any]) -> dict[str, Any]:
    """Map extraction to PickCard (type: 'pick', not 'bet')."""
    matchup_raw = extracted.get("matchup", "")
    if isinstance(matchup_raw, dict):
        matchup = {
            "home": matchup_raw.get("home", "—"),
            "away": matchup_raw.get("away", "—"),
        }
    elif isinstance(matchup_raw, str) and " vs " in matchup_raw.lower():
        parts = re.split(r"\s+(?:vs\.?|v)\s+", matchup_raw, flags=re.IGNORECASE)
        matchup = {"home": parts[0].strip(), "away": parts[-1].strip()}
    else:
        matchup = {"home": str(matchup_raw) if matchup_raw else "—", "away": "—"}

    return {
        "type": "pick",
        "title": extracted.get("matchup", "Bet Slip") if isinstance(matchup_raw, str) else
                 f"{matchup['home']} vs {matchup['away']}",
        "subtitle": _compact(
            extracted.get("bet_type", ""),
            extracted.get("odds", ""),
            extracted.get("stake", ""),
        ),
        "matchup": matchup,
        "sport": extracted.get("sport", "—"),
        "league": extracted.get("league", "—"),
        "line": extracted.get("line", extracted.get("odds", "—")),
        "impliedOdds": _parse_float(extracted.get("implied_odds", 0)),
        "recentMovement": extracted.get("recent_movement", "—"),
        "notes": extracted.get("notes", "—"),
        "valueRating": extracted.get("value_rating", "—"),
        "metadata": _extraction_metadata(extracted),
    }


def _build_receipt_card(extracted: dict[str, Any]) -> dict[str, Any]:
    """Map extraction to BaseCard (no ReceiptCard in schema)."""
    return {
        "type": "receipt",
        "title": extracted.get("merchant", "Receipt"),
        "subtitle": _compact(
            extracted.get("total", ""),
            extracted.get("date", ""),
        ),
        "metadata": _extraction_metadata(extracted),
    }


def _build_generic_card(extracted: dict[str, Any]) -> dict[str, Any]:
    """Fallback for unknown content types — BaseCard."""
    detected = extracted.get("detected_type", "unknown")
    nested = extracted.get("fields", {})
    meta = _extraction_metadata(extracted)
    if nested:
        meta.update(nested)

    return {
        "type": detected,
        "title": extracted.get("title", detected.replace("_", " ").title()),
        "metadata": meta,
    }


# ── Text formatter ───────────────────────────────────────────


def format_as_text(extracted: dict[str, Any], content_type: str) -> str:
    """Format extraction as human-readable text (for output_format='text')."""
    lines: list[str] = []
    confidence = extracted.get("confidence", 0)
    lines.append(f"Detected: {content_type} (confidence: {confidence:.0%})")
    lines.append("")

    text_content = extracted.get("text_content")
    if text_content:
        lines.append(str(text_content))
        lines.append("")

    for key, value in extracted.items():
        if key in _META_KEYS or key == "text_content":
            continue
        if value is None or value == "" or value == []:
            continue
        display_key = key.replace("_", " ").title()
        if isinstance(value, list):
            lines.append(f"  {display_key}: {', '.join(str(v) for v in value)}")
        elif isinstance(value, dict):
            lines.append(f"  {display_key}:")
            for k, v in value.items():
                lines.append(f"    {k}: {v}")
        else:
            lines.append(f"  {display_key}: {value}")

    for key, value in extracted.get("fields", {}).items():
        display_key = key.replace("_", " ").title()
        lines.append(f"  {display_key}: {value}")

    uncertain = extracted.get("uncertain_fields", [])
    if uncertain:
        lines.append(f"\n  ⚠ Uncertain: {', '.join(uncertain)}")

    return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────


def _parse_price(raw: Any) -> dict[str, Any]:
    """Best-effort parse of price strings like '$499', '€1,200', '2500 USD'.

    Returns: {"amount": float, "currency": str}
    """
    if isinstance(raw, dict):
        return {
            "amount": float(raw.get("amount", 0)),
            "currency": raw.get("currency", "USD"),
        }
    if isinstance(raw, (int, float)):
        return {"amount": float(raw), "currency": "USD"}

    s = str(raw).strip()
    if not s:
        return {"amount": 0, "currency": "USD"}

    # Detect currency from symbol prefix
    currency = "USD"
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if s.startswith(symbol):
            currency = code
            s = s[len(symbol):]
            break

    # Detect currency from suffix (e.g. "2500 EUR")
    suffix_match = re.search(r"\s+([A-Z]{3})$", s)
    if suffix_match:
        currency = suffix_match.group(1)
        s = s[: suffix_match.start()]

    # Extract numeric value
    s = s.replace(",", "").strip()
    num_match = re.search(r"[\d.]+", s)
    amount = float(num_match.group()) if num_match else 0

    return {"amount": amount, "currency": currency}


def _parse_float(raw: Any) -> float:
    """Safe float parse."""
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def _extraction_metadata(extracted: dict[str, Any]) -> dict[str, Any]:
    """Build metadata dict from non-card extraction fields."""
    return {
        k: v for k, v in extracted.items()
        if k not in _META_KEYS and v is not None and v != "" and v != []
    }


def _compact(*parts: str) -> str:
    """Join non-empty parts with ' · '."""
    return " · ".join(p for p in parts if p)
