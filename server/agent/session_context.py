"""
Read-Before-Act Verification — SessionContext

Tracks what the agent has actually verified (via tool calls) in each session.
Prevents hallucinated data from being presented as real:

- Soft check: warns if creating a card without first searching for real data
- Hard check: blocks payment approvals without prior tool-verified data

Usage:
    ctx = SessionContext()
    ctx.record_tool_call("bash_execute", "curl searxng...")
    ctx.has_searched()          # True
    ctx.has_real_data("flights") # True if search matched flight keywords
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ── Domain keyword patterns ──────────────────────────────────

_DOMAIN_PATTERNS: dict[str, list[str]] = {
    "flights": [
        "flight", "airline", "kayak", "skyscanner", "google flights",
        "expedia", "booking.com", "departure", "arrival", "airport",
    ],
    "apartments": [
        "apartment", "zillow", "trulia", "realtor", "rent", "lease",
        "redfin", "housing", "bedroom", "sqft",
    ],
    "betting": [
        "odds", "betting", "sportsbook", "draftkings", "fanduel",
        "bovada", "moneyline", "spread", "over/under", "parlay",
    ],
    "prices": [
        "price", "cost", "$", "usd", "ebay", "amazon", "stockx",
        "goat", "retail", "msrp", "cheapest",
    ],
}

# Card type → domain mapping
_CARD_DOMAIN_MAP: dict[str, str] = {
    "flight": "flights",
    "house": "apartments",
    "pick": "betting",
}

# Tools that count as real data sources
_DATA_TOOLS: set[str] = {
    "bash_execute",
    "http_request",
    "web_search",
    "browser",
}


# ── SessionContext ───────────────────────────────────────────

@dataclass
class SessionContext:
    """Tracks tool calls and verified data domains for a single session."""

    tool_calls: list[dict] = field(default_factory=list)
    verified_domains: set[str] = field(default_factory=set)
    files_written: set[str] = field(default_factory=set)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def record_tool_call(self, tool_name: str, command: str = "") -> None:
        """Record a tool call and detect verified data domains."""
        self.tool_calls.append({
            "tool": tool_name,
            "command": command,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Browser tool always counts as real data
        if tool_name == "browser":
            self.verified_domains.add("browser")

        # Check command text against domain patterns
        text = command.lower()
        for domain, keywords in _DOMAIN_PATTERNS.items():
            if any(kw in text for kw in keywords):
                self.verified_domains.add(domain)

    def record_file_write(self, path: str) -> None:
        """Track files written to /workspace/data/."""
        self.files_written.add(path)

    def has_searched(self) -> bool:
        """True if any data-producing tool was called."""
        return any(
            call["tool"] in _DATA_TOOLS for call in self.tool_calls
        )

    def has_real_data(self, domain: str) -> bool:
        """True if we have verified data for the given domain."""
        return domain in self.verified_domains

    def has_any_tool_calls(self) -> bool:
        """True if any tool calls have been recorded."""
        return len(self.tool_calls) > 0

    # ── Helper: card creation check ──────────────────────────

    def check_card_data(self, card_type: str, tool_input: dict) -> str | None:
        """Check if card creation has verified data backing it.

        Returns a warning string if unverified, None if OK.
        """
        domain = _CARD_DOMAIN_MAP.get(card_type)

        # Check price-related keys in tool_input
        if domain is None:
            price_keys = {"price", "cost", "amount", "total"}
            if price_keys & set(tool_input.keys()):
                domain = "prices"

        if domain is None:
            return None  # Unknown card type, no check needed

        if self.has_real_data(domain):
            return None  # Verified

        if not self.has_searched():
            return (
                f"[VERIFICATION REQUIRED] You are creating a '{card_type}' card "
                f"without having searched for real {domain} data first. "
                f"Use web_search, http_request, or browser to fetch live data "
                f"before presenting it to the user. Do NOT use training data."
            )

        # Searched but not for this domain
        return (
            f"[VERIFICATION WARNING] You searched for data but none matched "
            f"the '{domain}' domain. Please verify you have real {domain} data "
            f"before creating this card."
        )

    # ── Helper: payment readiness check ──────────────────────

    def check_payment_readiness(self) -> str | None:
        """Check if the session has enough verified data for a payment action.

        Returns a rejection string if not ready, None if OK.
        """
        if not self.has_any_tool_calls():
            return (
                "[PAYMENT BLOCKED] Cannot process payment without any prior "
                "tool calls. The agent must search for and verify real data "
                "before requesting payment approval."
            )

        if not self.has_searched():
            return (
                "[PAYMENT BLOCKED] Cannot process payment without having "
                "searched for real data. Use web_search, http_request, or "
                "browser to verify current prices before payment."
            )

        return None
