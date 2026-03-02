---
name: flight-search
description: Search for flights across providers, compare prices, rank by preferences, monitor for price drops.
tools: [http_request, code_execution, create_card, save_memory, request_approval]
approval_actions: [pay, submit]
version: "1.0.0"
author: ClawBot
tags: [travel, flights, booking, price-monitoring]
---

# Flight Search

## Context

This skill enables ClawBot to search for flights, compare prices across providers, rank results by user preferences, and optionally monitor for price drops.

**When to activate this skill:**
- User says "find flights", "search flights", "cheapest flight to X", "fly from X to Y"
- User asks about airfare, plane tickets, or routes between cities
- User wants to compare flight options or watch for price drops
- User mentions specific airlines, airports, or travel dates

**Capabilities:**
- Search real-time flight offers via Amadeus API (primary)
- Fall back to SerpAPI Google Flights when Amadeus credentials unavailable
- Rank results by price, duration, layovers, and refundability
- Output structured FlightCard data for the iOS app
- Save searches to memory for price monitoring
- Generate realistic mock results for development/demo


## Authentication

### Amadeus API (Primary)

Amadeus uses OAuth2 `client_credentials` flow. Before making any search request, you must obtain an access token.

**Step 1: Get access token**

```
Tool: http_request
{
  "method": "POST",
  "url": "https://test.api.amadeus.com/v1/security/oauth2/token",
  "headers": {"Content-Type": "application/x-www-form-urlencoded"},
  "body": "grant_type=client_credentials&client_id={{CLIENT_ID}}&client_secret={{CLIENT_SECRET}}",
  "credential": "amadeus"
}
```

Response contains `access_token` and `expires_in` (typically 1799 seconds / ~30 min).

**Step 2: Use token in subsequent requests**

Add header: `Authorization: Bearer {access_token}`

**Production vs Test:**
- Test: `https://test.api.amadeus.com` (free, rate-limited)
- Production: `https://api.amadeus.com` (requires paid plan)

### SerpAPI (Fallback)

SerpAPI uses a simple API key as a query parameter. No OAuth flow needed.

```
Tool: http_request
{
  "method": "GET",
  "url": "https://serpapi.com/search",
  "query_params": {"engine": "google_flights", ...},
  "credential": "serpapi"
}
```

### Credential Check

Before searching, check which credentials are available:

1. Check if `amadeus` credential exists -> use Amadeus API
2. Else check if `serpapi` credential exists -> use SerpAPI
3. Else -> use Mock Mode (generate demo results)


## API: Amadeus Flight Offers Search (Primary)

### Endpoint

```
GET https://test.api.amadeus.com/v2/shopping/flight-offers
Authorization: Bearer {access_token}
```

### Required Parameters

| Param | Type | Example | Description |
|-------|------|---------|-------------|
| `originLocationCode` | string | `"SFO"` | IATA code of departure airport |
| `destinationLocationCode` | string | `"LHR"` | IATA code of arrival airport |
| `departureDate` | string | `"2025-03-15"` | ISO date (YYYY-MM-DD) |
| `adults` | integer | `1` | Number of adult passengers |

### Optional Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `returnDate` | string | — | ISO date for round-trip return |
| `children` | integer | `0` | Number of child passengers (2-11) |
| `infants` | integer | `0` | Number of infant passengers (<2) |
| `travelClass` | string | — | `ECONOMY`, `PREMIUM_ECONOMY`, `BUSINESS`, `FIRST` |
| `nonStop` | boolean | `false` | Only show nonstop flights |
| `maxPrice` | integer | — | Max price per traveler |
| `max` | integer | `250` | Max number of results (use 20-50) |
| `currencyCode` | string | `"USD"` | Price currency |

### Example Request

```
Tool: http_request
{
  "method": "GET",
  "url": "https://test.api.amadeus.com/v2/shopping/flight-offers",
  "headers": {"Authorization": "Bearer {access_token}"},
  "query_params": {
    "originLocationCode": "SFO",
    "destinationLocationCode": "LHR",
    "departureDate": "2025-03-15",
    "adults": "1",
    "nonStop": "false",
    "max": "30",
    "currencyCode": "USD"
  }
}
```

### Response Parsing

The Amadeus response is deeply nested. Here is the structure:

```
{
  "data": [
    {
      "id": "1",
      "source": "GDS",
      "instantTicketingRequired": false,
      "numberOfBookableSeats": 9,
      "itineraries": [
        {
          "duration": "PT10H30M",
          "segments": [
            {
              "departure": {
                "iataCode": "SFO",
                "terminal": "I",
                "at": "2025-03-15T17:00:00"
              },
              "arrival": {
                "iataCode": "LHR",
                "terminal": "5",
                "at": "2025-03-16T11:30:00"
              },
              "carrierCode": "BA",
              "number": "286",
              "aircraft": {"code": "777"},
              "duration": "PT10H30M",
              "numberOfStops": 0
            }
          ]
        }
      ],
      "price": {
        "currency": "USD",
        "total": "489.00",
        "grandTotal": "489.00",
        "base": "389.00"
      },
      "travelerPricings": [
        {
          "fareDetailsBySegment": [
            {
              "cabin": "ECONOMY",
              "class": "V",
              "includedCheckedBags": {"weight": 23, "weightUnit": "KG"}
            }
          ]
        }
      ]
    }
  ],
  "dictionaries": {
    "carriers": {"BA": "BRITISH AIRWAYS", "UA": "UNITED AIRLINES"},
    "aircraft": {"777": "BOEING 777", "789": "BOEING 787-9"}
  }
}
```

**Parsing instructions:**

1. **Carrier name:** Look up `segment.carrierCode` in `dictionaries.carriers`
2. **Total price:** Use `data[i].price.grandTotal` (string, parse to float)
3. **Duration:** Parse `itineraries[0].duration` from ISO 8601 duration (e.g., `PT10H30M` = 10 hours 30 minutes)
4. **Stops:** Count `segments.length - 1` per itinerary. Extract layover cities from intermediate arrival airports.
5. **Cabin class:** `travelerPricings[0].fareDetailsBySegment[0].cabin`
6. **Baggage:** Check `includedCheckedBags` in travelerPricings. If missing, note "Carry-on only"
7. **Flight number:** Combine `carrierCode` + `number` (e.g., "BA 286")
8. **Departure/Arrival times:** Use `segments[0].departure.at` and `segments[last].arrival.at`

**Duration parsing helper (use code_execution):**

```python
import re
def parse_duration(iso_dur):
    """Convert PT10H30M to total minutes and display string."""
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', iso_dur)
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total_min = hours * 60 + minutes
    return total_min, f"{hours}h {minutes:02d}m"
```


## API: SerpAPI Google Flights (Alternative)

Use when Amadeus credentials are not available.

### Endpoint

```
GET https://serpapi.com/search
```

### Parameters

| Param | Type | Example | Description |
|-------|------|---------|-------------|
| `engine` | string | `"google_flights"` | Required, always this value |
| `departure_id` | string | `"SFO"` | Departure airport IATA code |
| `arrival_id` | string | `"LHR"` | Arrival airport IATA code |
| `outbound_date` | string | `"2025-03-15"` | Departure date |
| `return_date` | string | — | Return date (omit for one-way) |
| `type` | integer | `1` | 1=round-trip, 2=one-way |
| `currency` | string | `"USD"` | Price currency |
| `hl` | string | `"en"` | Language |
| `api_key` | string | — | Injected via credential store |

### Response Parsing

SerpAPI returns a simpler structure:

```json
{
  "best_flights": [...],
  "other_flights": [...],
  "price_insights": {
    "lowest_price": 389,
    "typical_price_range": [400, 700]
  }
}
```

Each flight object contains:
- `flights[].airline` — Airline name (not code)
- `flights[].departure_airport`, `flights[].arrival_airport` — Airport objects
- `flights[].duration` — Duration in minutes
- `flights[].price` — Total price as integer
- `flights[].stops` — Number of stops
- `flights[].layovers` — Array of layover objects


## IATA Codes Reference

Common airport codes the agent should recognize:

| Code | City | Country |
|------|------|---------|
| JFK | New York (Kennedy) | US |
| LGA | New York (LaGuardia) | US |
| EWR | Newark | US |
| LAX | Los Angeles | US |
| SFO | San Francisco | US |
| ORD | Chicago (O'Hare) | US |
| ATL | Atlanta | US |
| DFW | Dallas/Fort Worth | US |
| MIA | Miami | US |
| SEA | Seattle | US |
| BOS | Boston | US |
| DEN | Denver | US |
| IAD | Washington (Dulles) | US |
| LHR | London (Heathrow) | UK |
| LGW | London (Gatwick) | UK |
| CDG | Paris (De Gaulle) | FR |
| FRA | Frankfurt | DE |
| AMS | Amsterdam | NL |
| FCO | Rome | IT |
| MAD | Madrid | ES |
| NRT | Tokyo (Narita) | JP |
| HND | Tokyo (Haneda) | JP |
| SIN | Singapore | SG |
| HKG | Hong Kong | HK |
| DXB | Dubai | AE |
| SYD | Sydney | AU |
| ICN | Seoul (Incheon) | KR |
| YYZ | Toronto | CA |
| MEX | Mexico City | MX |
| GRU | Sao Paulo | BR |

When users say city names instead of codes, resolve to the primary airport code. If a city has multiple airports (e.g., New York: JFK, LGA, EWR), default to the primary international one (JFK) and mention alternatives.


## Ranking Algorithm

Score and rank each flight offer using these weighted factors:

### Price Score (40% weight)
Normalize price relative to the cheapest and most expensive options in the result set.

```
price_score = 1.0 - (price - min_price) / (max_price - min_price)
```

If all prices are equal: `price_score = 1.0`

### Duration Score (25% weight)
Normalize total travel time. Lower duration is better.

```
duration_score = 1.0 - (duration_min - min_duration) / (max_duration - min_duration)
```

If all durations are equal: `duration_score = 1.0`

### Layovers Score (20% weight)
Fewer stops are better.

| Stops | Score |
|-------|-------|
| 0 (nonstop) | 1.0 |
| 1 | 0.6 |
| 2+ | 0.3 |

### Refundability Score (15% weight)
More flexible fares score higher.

| Policy | Score |
|--------|-------|
| Refundable | 1.0 |
| Partially refundable / change fees | 0.5 |
| Non-refundable | 0.0 |

### Combined Score

```
total = (price_score * 0.40) + (duration_score * 0.25) + (layovers_score * 0.20) + (refund_score * 0.15)
```

### Label Assignment

After computing scores for all flights:

| Label | Criteria |
|-------|----------|
| **Best Overall** | Highest combined score |
| **Cheapest** | Lowest `price.grandTotal` |
| **Fastest** | Shortest total duration |
| **Best for Points** | Most airline partnerships (Star Alliance, SkyTeam, Oneworld) or best mileage earning potential |

A single flight may receive at most one label. Priority: Best Overall > Cheapest > Fastest > Best for Points. If a flight wins multiple, use the highest priority.


## Card Output

For each top result, create a FlightCard using the `create_card` tool. The metadata must match the `FlightCard` interface in `shared/types/cards.ts`.

```
Tool: create_card
{
  "type": "flight",
  "id": "flight-ba286-sfo-lhr-20250315",
  "title": "BA 286 — SFO to LHR",
  "subtitle": "British Airways | Nonstop | Economy",
  "createdAt": "2025-03-01T12:00:00Z",
  "airline": "British Airways",
  "route": {"from": "SFO", "to": "LHR"},
  "departure": "2025-03-15T17:00:00Z",
  "arrival": "2025-03-16T11:30:00+00:00",
  "duration": "10h 30m",
  "layovers": 0,
  "price": {"amount": 489.00, "currency": "USD"},
  "baggage": "1 checked bag (23kg)",
  "refundPolicy": "Non-refundable",
  "pointsValue": {"program": "Oneworld", "points": 5500},
  "ranking": {
    "label": "Best Overall",
    "reason": "Best combination of price ($489), nonstop route, and travel time (10h 30m)"
  },
  "metadata": {
    "flightNumber": "BA 286",
    "cabin": "ECONOMY",
    "aircraft": "Boeing 777"
  },
  "actions": [
    {
      "id": "book-ba286",
      "label": "View on British Airways",
      "type": "link",
      "url": "https://www.britishairways.com"
    },
    {
      "id": "watch-ba286",
      "label": "Watch Price",
      "type": "custom",
      "payload": {"action": "watch_price", "flight_id": "ba286-sfo-lhr-20250315"}
    }
  ],
  "source": "Amadeus"
}
```

**Present the top 5 results** as FlightCards, sorted by ranking score descending. Always include the Cheapest and Fastest flights even if they aren't in the top 5 by combined score.


## Price Monitoring

When a user asks to "watch" or "monitor" a flight's price:

### Saving a Watch

```
Tool: save_memory
{
  "key": "watch-price-sfo-lhr-20250315",
  "content": "# Flight Price Watch: SFO → LHR\n\n**Date:** 2025-03-15\n**Best Price:** $489 (British Airways BA 286, nonstop)\n**Search Time:** 2025-03-01T15:30:00Z\n**Passengers:** 1 adult\n**Class:** Economy\n\n## Price History\n- 2025-03-01: $489 (BA 286)\n\n## Search Params\n- origin: SFO\n- destination: LHR\n- date: 2025-03-15\n- adults: 1\n- class: ECONOMY",
  "tags": ["active-watch", "flights", "sfo", "lhr"]
}
```

### Checking a Watch

When the agent periodically checks watches (or user asks "any price drops?"):

1. Search memory for `active-watch` tagged entries
2. Re-run the flight search with saved params
3. Compare current best price to saved best price
4. If lower: notify user with the price drop amount
5. Update the memory entry with new price and timestamp


## Mock Mode

When neither `amadeus` nor `serpapi` credentials are available, generate realistic demo results.

### How to Detect Mock Mode

Check credential availability before searching. If no credentials exist, proceed with mock data.

### Mock Flight Generation

Generate 8-12 flights with realistic variety:

**Airlines to mix:** United, Delta, American, Southwest, JetBlue, Alaska, British Airways, Lufthansa, Virgin Atlantic, KLM, Air France

**Route-appropriate pricing:**
- Domestic US: $150-$600
- US to Europe: $400-$1,400
- US to Asia: $500-$2,000
- Short-haul (< 3 hours): $80-$300

**Variety requirements:**
- At least 2 nonstop flights (if route supports it)
- At least 2 one-stop flights
- At least 1 two-stop flight
- At least 1 refundable option
- Price spread: cheapest should be ~60% of most expensive
- Duration spread: fastest nonstop to longest 2-stop

**Realistic layover cities:**
- US domestic: ORD, DEN, DFW, ATL, IAH
- US to Europe: JFK, BOS, IAD, ORD, PHL
- US to Asia: LAX, SFO, SEA, NRT, ICN

### Presentation

When showing mock results, prepend this notice:

> **Demo Results** — These are simulated flights for demonstration. Connect your Amadeus or SerpAPI credentials for live data. Run: `python -m server.agent.credential_store add`

Then present FlightCards exactly as you would for real results (with ranking, sorting, labels).


## Example Interaction

**User:** "Find me flights from SFO to London next Friday, returning the following Sunday"

**Agent thinking:**
1. Resolve "next Friday" and "following Sunday" to specific ISO dates
2. Resolve "London" to LHR (primary) — mention LGW as alternative
3. Check credentials: amadeus -> serpapi -> mock
4. Execute search
5. Parse and rank results
6. Create FlightCards for top 5

**Agent response:**

"I'll search for round-trip flights from SFO to London Heathrow (LHR), departing Friday March 14 and returning Sunday March 16. Searching now..."

[Executes API call or generates mock data]

"Found 24 options. Here are the top 5:"

[Presents 5 FlightCards with labels: Best Overall, Cheapest, Fastest, etc.]

"Prices range from $389 to $1,250. The nonstop British Airways flight at $489 offers the best overall value. Want me to watch any of these for price drops?"

**User:** "Watch the cheapest one for price drops"

**Agent:** "Done — I'll monitor the Norse Atlantic flight at $389 (SFO→LHR, March 14). I'll let you know if the price changes."

[Saves to memory with active-watch tag]


## Rules

1. **Always confirm details before searching:** Verify dates, passenger count, cabin class, and airports. If ambiguous ("next week"), resolve to specific dates and confirm with the user.

2. **Present results sorted by ranking score** with clear labels. Show at minimum the top 5 results.

3. **Include price disclaimer:** After results, add: "Prices may vary. Check airline website for current pricing."

4. **Never auto-book:** Booking requires user approval via `request_approval` tool with action type `pay`. The agent presents options — the user decides.

5. **Handle API errors gracefully:** If Amadeus returns an error (rate limit, invalid params, server error), try SerpAPI. If both fail, offer mock results and explain the situation.

6. **Respect user preferences from memory:** Before searching, check memory for `flight-preferences` key. Apply any saved preferences (preferred airline, seat type, alliance, home airport).

7. **Date handling:** Always use ISO 8601 format (YYYY-MM-DD) for API calls. Convert relative dates ("next Friday", "in 2 weeks") to absolute dates. Always show the resolved date to the user for confirmation.

8. **Multi-city/complex itineraries:** This skill handles one-way and round-trip searches. For multi-city itineraries, make separate searches for each leg and present them together.
