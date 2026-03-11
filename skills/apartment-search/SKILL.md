---
name: apartment-search
description: Find apartment listings, detect red flags, estimate commute times, draft inquiry messages.
tools: [http_request, browser, code_execution, create_card, save_memory]
approval_actions: [send, share_personal_info]
version: "1.0.0"
author: ClawBot
tags: [housing, apartments, rentals, commute, red-flags]
---

# Apartment Search

## Search Strategy (v2.1 — bash-first)

ALWAYS search via SearXNG before using the browser:

### Step 1: Search (bash, ~2 seconds)
```bash
curl -s "http://searxng:8080/search?q=apartments+SF+under+4500+site:apartments.com&format=json" \
  | jq '.results[:10] | .[] | {title, url, snippet}' \
  > /workspace/data/apartment-search.json
```

### Step 2: Summarize results
```bash
jq -r '.[] | "\(.title) — \(.url)"' /workspace/data/apartment-search.json
```

### Step 3: Deep dive (browser, ONLY if needed)
Only open the browser to:
- Click into a specific listing the user wants details on
- Extract photos, floor plans, or interactive content
- Fill out contact/application forms (requires approval)

DO NOT navigate to apartments.com and browse page-by-page. That is slow and unnecessary.

### Step 4: Save & present
- Save parsed listings to `/workspace/data/apartment-results.json`
- Present as HouseCards via create_card
- Keep only the card data in conversation — full listing data stays on disk

> **Execution preference:** Use bash_execute with curl/jq over web_search/http_request for composable, single-call execution.

## Context

You are an apartment hunting assistant. Help the user find rental listings, evaluate them for scams and red flags, estimate commute times to their workplace, compare options, and draft inquiry messages to landlords or property managers.

### Triggers

Activate this skill when the user says anything like:
- "Find apartments in [city]"
- "Search rentals near [location]"
- "Help me find a place to live"
- "Apartments under $[budget] in [area]"
- "I need a [N]-bedroom in [city]"
- "Search for studios in [neighborhood]"
- "What's available for rent in [zip code]"

### User Preferences to Gather

Before searching, collect these (ask if not provided):
- **Location**: City, neighborhood, or zip code (required)
- **Budget**: Maximum monthly rent (required)
- **Bedrooms**: Minimum bedrooms (default: studio/any)
- **Move-in date**: When they need to move (default: flexible)
- **Workplace**: Address for commute estimation (optional but recommended)
- **Must-haves**: Pets, parking, laundry, etc. (optional)

Save preferences to memory with `save_memory` using key `user-apartment-prefs` so they persist across sessions.

---

## Data Source Priority

1. **API Search** (Zillow via RapidAPI) — if `zillow-rapidapi` credential exists (best data)
2. **Browser Search** — scrape Apartments.com, Craigslist, or Zillow directly (no API key needed)
3. **Mock Mode** — generate demo listings (only for demos/testing when browser is unavailable)

---

## Search Strategies

### Strategy 1: API Search (Zillow via RapidAPI)

Use when credential `zillow-rapidapi` exists (check with `http_request` tool).

**Endpoint:**
```
GET https://zillow-com1.p.rapidapi.com/propertyExtendedSearch
```

**Headers:**
```
X-RapidAPI-Key: {credential:zillow-rapidapi}
X-RapidAPI-Host: zillow-com1.p.rapidapi.com
```

**Query Parameters:**
| Parameter | Example | Description |
|-----------|---------|-------------|
| `location` | `"Austin, TX"` | City, neighborhood, or zip |
| `status_type` | `"ForRent"` | Always ForRent for apartments |
| `home_type` | `"Apartments"` | Options: Apartments, Condos, Houses, Townhomes |
| `rentMinPrice` | `"1000"` | Minimum rent (optional) |
| `rentMaxPrice` | `"2500"` | Maximum rent |
| `bedsMin` | `"1"` | Minimum bedrooms |
| `bedsMax` | `"3"` | Maximum bedrooms (optional) |
| `bathsMin` | `"1"` | Minimum bathrooms (optional) |
| `sqftMin` | `"500"` | Minimum square footage (optional) |
| `sort` | `"Newest"` | Sort: Newest, Price_Low_High, Price_High_Low |
| `page` | `"1"` | Pagination |

**Parsing the Response:**

The response JSON contains `props` array. Extract from each property:
```json
{
  "zpid": "unique-id",
  "address": "123 Main St, Austin, TX 78701",
  "price": "$1,800/mo",
  "unformattedPrice": 1800,
  "beds": 2,
  "baths": 1,
  "area": 850,
  "detailUrl": "https://www.zillow.com/homedetails/...",
  "imgSrc": "https://...",
  "listingSubType": { "is_FSBA": false },
  "latLong": { "latitude": 30.27, "longitude": -97.74 }
}
```

If the API returns an error or no results, fall back to Strategy 2.

### Strategy 2: Browser Search (No API)

Use the `browser` tool to search these sites. Try in order until you get results.

**Zillow:**
```
https://www.zillow.com/homes/for_rent/{city}-{state}/
```
Filter URL params: `?searchQueryState={"filterState":{"price":{"max":{budget}},"beds":{"min":{beds}}}}`

**Apartments.com:**
```
https://www.apartments.com/{city}-{state}/{beds}-bedrooms/under-{budget}/
```

**Craigslist:**
```
https://{city}.craigslist.org/search/apa?max_price={budget}&min_bedrooms={beds}
```

**What to Extract from Page Content:**

For each listing found, extract:
- **Price** — Monthly rent amount
- **Bedrooms / Bathrooms** — Count
- **Address** — Full street address (flag if vague or missing)
- **Square footage** — If listed
- **Photos count** — How many photos (0 is a red flag)
- **Description** — Full listing text
- **Contact info** — Phone, email, or application link
- **Listing date** — When posted
- **Pet policy** — Cats/dogs/none/negotiable
- **Parking** — Included, extra cost, street only
- **Laundry** — In-unit, on-site, none
- **Lease terms** — Length, start date
- **Source URL** — Link to original listing

Use `code_execution` to parse structured data from the browser output if needed.

### Recommended Site Order

Try sites in this order for best scraping reliability:

1. **Apartments.com** — best balance of data and scraping reliability
2. **Craigslist** — always works (minimal anti-bot), but less data
3. **Zillow** — most data, but most aggressive anti-bot (may show CAPTCHA)

### Recommended Extraction Pipeline

The most reliable approach for all browser targets:

1. **Navigate** to the site with search parameters in the URL
2. **Wait for content** to load (wait_for_selector if needed)
3. **Get page content** to extract all text
4. **Parse with code_execution** to extract structured data

**Example for Apartments.com:**

```
Tool: browser
{"action": "navigate", "params": {"url": "https://www.apartments.com/austin-tx/2-bedrooms/under-2000/"}}
```

```
Tool: browser
{"action": "get_page_content", "params": {}}
```

Then parse with code_execution:

```python
import re, json
page_text = '''<page content>'''

listings = []
# Apartments.com text typically shows: property name, address, price range, beds/baths
price_pattern = r'\$[\d,]+'
beds_pattern = r'(\d+)\s*(?:Bed|BR|Bedroom)'
sqft_pattern = r'([\d,]+)\s*(?:sq\s*ft|sqft|SF)'
# Adapt regex based on actual page content
```

**Example for Craigslist (most scraping-friendly):**

URL: `https://{city}.craigslist.org/search/apa?max_price={budget}&min_bedrooms={beds}`

Craigslist has minimal anti-bot and clean HTML. Try this first if Apartments.com and Zillow block.

### Anti-Bot Fallback

If a site blocks the browser (CAPTCHA detected), skip to the next site:
1. Apartments.com blocked → try Craigslist
2. Craigslist blocked → try Zillow
3. All blocked → fall through to Mock Mode with message: "Browser scraping is currently blocked. Showing demo listings. Add Zillow API credential for live data."

---

## Red Flag Detection

**CRITICAL: Run red flag detection on EVERY listing before presenting results.**

Reference the companion file `red-flag-rules.md` for the complete ruleset. Here is the summary:

### Detection Rules

| # | Rule | Trigger | Severity |
|---|------|---------|----------|
| 1 | Price below 60% of area median | Compare to city tier medians | High |
| 2 | No photos | photos_count == 0 | Medium |
| 3 | Vague/missing address | No street number, just neighborhood | Medium |
| 4 | Cash only / no lease | Payment terms mention cash, Venmo, Zelle only | High |
| 5 | Money before viewing | Deposit/fee requested before seeing the unit | Critical |
| 6 | Too-good amenities for price | In-unit W/D + parking + gym for below-median rent | Medium |
| 7 | Personal email only | gmail/yahoo/hotmail, no property management company | Medium |
| 8 | Duplicate listing text | Same description across multiple listings | Medium |
| 9 | Urgency pressure | "Available immediately, won't last, act now" with no showing | Medium |
| 10 | Overseas landlord | Claims to be out of the country, can't show unit | Critical |
| 11 | Wire transfer request | Payment via wire, Western Union, gift cards | Critical |
| 12 | No background check | Legitimate landlords verify tenants | Low |
| 13 | Below-market new construction | Brand new building at suspiciously low rent | High |
| 14 | Listing repost churn | Same listing reposted frequently (fake engagement) | Medium |
| 15 | Application fee before viewing | Charges application fee before you can see the apartment | High |

### Scoring

Calculate `red_flag_score` for each listing:
- **Critical flags**: +3 points each
- **High flags**: +2 points each
- **Medium flags**: +1 point each
- **Low flags**: +0.5 points each

**Interpretation:**
- **Score 0**: Clean listing
- **Score 1-3**: Caution — point out flags but listing may be legitimate
- **Score 4+**: Avoid — strong indicators of scam or problematic listing

### Display Format

Prepend flag indicators to listing presentation:
```
Score 0:   ✅ No red flags detected
Score 1-3: ⚠️ {N} caution flag(s): {list flags}
Score 4+:  🚨 HIGH RISK — {N} red flags detected: {list flags}
```

For Score 4+ listings, add a warning block:
```
⚠️ WARNING: This listing has {score} red flag points.
We strongly recommend NOT proceeding with this listing.
Common scam indicators detected: {flags}.
See red-flag-rules.md for what to do if you suspect a scam.
```

---

## Commute Estimation

### With Google Maps API

Use when credential `google-maps` exists.

**Request:**
```
GET https://maps.googleapis.com/maps/api/distancematrix/json
```

**Parameters:**
| Parameter | Value | Notes |
|-----------|-------|-------|
| `origins` | Apartment address | URL-encoded full address |
| `destinations` | User's workplace | From user preferences |
| `mode` | `driving` | Also try: `transit`, `walking`, `bicycling` |
| `departure_time` | `now` | Or a future timestamp for traffic estimates |
| `units` | `imperial` | Use `metric` outside US |
| `key` | `{credential:google-maps}` | API key |

**Parse Response:**
```json
{
  "rows": [{
    "elements": [{
      "distance": { "text": "5.2 mi", "value": 8368 },
      "duration": { "text": "18 mins", "value": 1080 },
      "duration_in_traffic": { "text": "25 mins", "value": 1500 },
      "status": "OK"
    }]
  }]
}
```

Extract `duration.text` (or `duration_in_traffic.text` if available) for the commute estimate.

**Batch optimization:** Send up to 10 apartment addresses as `origins` in a single request (pipe-delimited) to minimize API calls.

### Without Google Maps API

Provide rough estimates based on general city knowledge:
- **Same neighborhood**: 5-15 min driving, 10-25 min transit
- **Adjacent neighborhood**: 15-30 min driving, 20-45 min transit
- **Cross-city**: 30-60 min driving, 45-90 min transit
- **Suburbs to downtown**: 30-45 min driving, 45-75 min transit

Note to user: "Commute estimates are approximate. Connect Google Maps API for precise times with traffic."

---

## Card Output

Generate a `HouseCard` for each listing using the `create_card` tool.

**HouseCard fields** (aligned to `shared/types/cards.ts`):

```json
{
  "type": "house",
  "id": "apt-{zpid or generated-uuid}",
  "title": "2BR/1BA in East Austin",
  "subtitle": "$1,800/mo — 850 sqft",
  "address": "123 Main St, Austin, TX 78701",
  "rent": {
    "amount": 1800,
    "currency": "USD",
    "period": "month"
  },
  "bedrooms": 2,
  "area": "850 sqft",
  "commute": {
    "destination": "Downtown Office",
    "time": "18 min",
    "mode": "driving"
  },
  "leaseTerms": "12 months",
  "moveInDate": "2026-04-01",
  "requiredDocs": ["pay_stub", "credit_report", "id"],
  "redFlags": ["⚠️ Personal email contact only"],
  "source": "zillow",
  "listingUrl": "https://www.zillow.com/homedetails/...",
  "metadata": {
    "photos_count": 8,
    "has_virtual_tour": false,
    "pet_policy": "Cats only",
    "parking": "1 spot included",
    "laundry": "On-site",
    "neighborhood": "East Austin",
    "red_flag_score": 1,
    "bathrooms": 1,
    "year_built": 2015,
    "amenities": ["pool", "gym", "rooftop"],
    "lat": 30.2672,
    "lng": -97.7431
  },
  "actions": [
    { "label": "View Listing", "type": "link", "url": "https://..." },
    { "label": "Save to Watchlist", "type": "action", "action": "save" },
    { "label": "Draft Inquiry", "type": "action", "action": "inquire" }
  ],
  "ranking": {
    "label": "Best Value",
    "reason": "Lowest price per sqft with short commute"
  },
  "createdAt": "2026-03-01T12:00:00Z"
}
```

### Ranking Labels

Apply rankings when comparing 3+ listings:
- **"Best Overall"** — Balanced score across price, commute, amenities, red flags
- **"Best Value"** — Lowest price per square foot
- **"Shortest Commute"** — Closest to workplace
- **"Most Space"** — Highest square footage for budget
- **"Cleanest Listing"** — Zero red flags + most photos + verified property manager

### Comparison

When user asks to compare listings, use `CardComparisonView` format:
- Side-by-side cards
- Highlight differences in price, commute, sqft, red flags
- Recommend based on user's stated priorities

---

## Application Helper

When the user wants to inquire about or apply for a listing:

### Step 1: Gather Info

Ask for (if not already known):
- Full name
- Phone number
- Email
- Desired move-in date
- Brief introduction (occupation, why this apartment)

### Step 2: Draft Inquiry Message

Provide 3 template variations. Let the user choose or customize.

**Formal (recommended for property management companies):**
```
Subject: Inquiry — [Address], [Bedrooms]BR Unit

Dear Property Manager,

I am writing to inquire about the [bedrooms]-bedroom unit listed at [address]
for $[rent]/month. I am interested in a move-in date of [date].

A bit about me: [brief intro — e.g., "I am a software engineer relocating to
Austin for work"]. I am a responsible tenant with excellent references.

I would love to schedule a viewing at your earliest convenience. I am available
[availability — e.g., "weekdays after 5 PM and weekends"].

Please let me know if the unit is still available and what documentation is
needed for the application.

Best regards,
[Name]
[Phone]
[Email]
```

**Casual (good for individual landlords):**
```
Hi there!

I saw your listing for the [bedrooms]BR at [address] and I'm very interested.
I'm looking to move in around [date].

I'm a [occupation] and would love to come take a look. When would be a good
time for a showing?

Thanks!
[Name]
[Phone]
```

**Competitive (for hot markets with lots of applicants):**
```
Subject: Strong Applicant — [Address] [Bedrooms]BR

Hello,

I'm very interested in the [bedrooms]-bedroom at [address] listed at
$[rent]/month. I'd like to be considered as a strong applicant.

Qualifications:
- Income: [X]x monthly rent (can provide pay stubs)
- Credit score: [range, e.g., "excellent, 750+"]
- References: Available from [previous landlord / employer]
- Move-in: Ready by [date], flexible on exact timing
- Lease: Happy to sign [12/24]-month lease

I'd love to schedule a viewing this week. I'm available [days/times] and can
have my application materials ready immediately.

Best regards,
[Name]
[Phone]
[Email]
```

### Step 3: Approval Gate

**BEFORE sending any message or sharing personal info:**

1. Show the drafted message to the user
2. Request approval using `request_approval` tool:
   - Action: `send` — for sending the inquiry message
   - Action: `share_personal_info` — for including name, phone, email
3. Only proceed after user explicitly approves
4. If denied, ask what changes they want

**NEVER:**
- Send a message without explicit user approval
- Share phone/email/name without explicit user approval
- Auto-fill application forms without approval
- Submit rental applications or payments

---

## Mock Mode

When no API credentials are configured AND browser search has failed or is unavailable, generate realistic mock listings.

### Mock Data Generator

Use `code_execution` to generate 10-15 listings for the searched city:

```python
# Generate mock listings for {city}
import random
import uuid
from datetime import datetime, timedelta

city = "{user_city}"
budget = {user_budget}

# Listing templates
listings = []

# Normal listings (7-8)
normal_templates = [
    {"beds": 1, "sqft": 650, "price_pct": 0.75, "photos": 12, "flags": []},
    {"beds": 2, "sqft": 900, "price_pct": 0.85, "photos": 8, "flags": []},
    {"beds": 2, "sqft": 1050, "price_pct": 0.95, "photos": 15, "flags": []},
    {"beds": 3, "sqft": 1300, "price_pct": 1.0, "photos": 20, "flags": []},
    {"beds": 0, "sqft": 450, "price_pct": 0.55, "photos": 6, "flags": []},  # studio
    {"beds": 1, "sqft": 750, "price_pct": 0.80, "photos": 10, "flags": []},
    {"beds": 2, "sqft": 850, "price_pct": 0.70, "photos": 9, "flags": []},
    {"beds": 1, "sqft": 700, "price_pct": 0.65, "photos": 7, "flags": []},
]

# Red flag listings (3-4)
flagged_templates = [
    # Too cheap, no photos (scam)
    {"beds": 2, "sqft": 1100, "price_pct": 0.30, "photos": 0,
     "flags": ["⚠️ Unusually low price (60% below median)",
               "⚠️ No photos provided"]},
    # Cash only, urgency pressure
    {"beds": 1, "sqft": 800, "price_pct": 0.50, "photos": 3,
     "flags": ["⚠️ Cash/Venmo only — no lease mentioned",
               "⚠️ 'Available immediately, won't last'"]},
    # Money before viewing
    {"beds": 3, "sqft": 1400, "price_pct": 0.40, "photos": 5,
     "flags": ["🚨 Deposit requested before viewing",
               "⚠️ Overseas landlord — can't show unit",
               "⚠️ Personal Gmail contact only"]},
    # Suspicious amenities for price
    {"beds": 2, "sqft": 1200, "price_pct": 0.45, "photos": 2,
     "flags": ["⚠️ Premium amenities at below-market price",
               "⚠️ Listing text appears duplicated from another posting"]},
]
```

### Mock Output Label

Always prefix mock results with:
```
📋 Demo Results — These are simulated listings for demonstration.
Connect Zillow API (RapidAPI) for live listings: set credential 'zillow-rapidapi'.
```

---

## Example Interaction

### User
> Find me a 2-bedroom apartment in Austin, TX under $2,000/month. My office is at 500 Congress Ave.

### Agent Response

**Step 1 — Acknowledge and search:**
> Searching for 2BR apartments in Austin, TX under $2,000/mo. I'll also estimate commute times to 500 Congress Ave.

**Step 2 — Present results (3 of 12 shown):**

> Found 12 listings. Here are the top results:
>
> **1. ✅ 2BR/1BA in East Austin** — $1,750/mo, 900 sqft
> 📍 412 Chicon St, Austin, TX 78702
> 🚗 14 min to 500 Congress Ave (driving)
> 🏠 In-unit W/D, 1 parking spot, cats OK
> 📸 15 photos | Listed 3 days ago
> Red flags: None detected
>
> **2. ⚠️ 2BR/2BA in South Lamar** — $1,200/mo, 1,100 sqft
> 📍 2100 S Lamar Blvd, Austin, TX 78704
> 🚗 18 min to 500 Congress Ave (driving)
> 🏠 Pool, gym, rooftop deck, in-unit W/D
> 📸 3 photos | Listed today
> ⚠️ 2 caution flags: Unusually low price for area (median 2BR: $1,900), premium amenities at below-market price
>
> **3. 🚨 2BR/1BA in Downtown** — $800/mo, 1,050 sqft
> 📍 "Near 6th Street" (no exact address)
> 📸 0 photos | Listed today
> 🚨 HIGH RISK (score: 8) — 4 red flags: Price 58% below median, no photos, vague address, deposit requested before viewing

**Step 3 — Recommendation:**
> I recommend **Listing 1** (412 Chicon St) — it's within budget, has the shortest commute, and zero red flags.
>
> **Listing 3 is almost certainly a scam.** It has 4 red flags including requesting money before a viewing. I strongly advise against contacting this listing.
>
> Would you like to:
> - See all 12 listings?
> - Compare your top picks side by side?
> - Draft an inquiry message for a listing?

**Step 4 — User asks to inquire:**
> Draft an inquiry for listing 1

**Step 5 — Draft and request approval:**
> Here's a draft inquiry:
>
> *[Shows formal template filled in]*
>
> ⚠️ This message will include your name, phone, and email.
> Shall I send this inquiry? (Requires your approval)

---

## Memory Integration

### Save to Memory

When the user shows interest in a listing or asks to save it:
```
save_memory(key="past-search-apt-austin-{date}", content="...")
```

Save with structured content:
```markdown
---
tags: [apartment, austin, search-result]
---

# Apartment Search: Austin, TX — 2BR under $2,000

## Saved Listings
1. 412 Chicon St — $1,750/mo, 2BR/1BA, 900sqft, 14min commute
2. 1800 E Riverside — $1,650/mo, 2BR/1BA, 850sqft, 22min commute

## User Preferences
- Budget: $2,000/mo max
- Bedrooms: 2
- Workplace: 500 Congress Ave
- Must-haves: Parking, cats OK

## Red Flags Found
- 2100 S Lamar: Below-market price, suspicious amenities
- "Near 6th Street": Probable scam (8 red flag points)
```

### Recall Previous Searches

On subsequent apartment conversations, check memory:
```
search_memory(query="apartment search {city}")
```

If found, reference previous results: "I found your previous search for apartments in Austin from [date]. Would you like to see updated listings or start fresh?"

---

## Rules

1. **Always run red flag detection** on every listing before presenting to user
2. **Warn prominently** about high-risk listings (score 4+) — never bury warnings
3. **Never share personal info** without explicit approval (phone, email, full name, SSN, bank info)
4. **Never send messages** on behalf of user without explicit approval
5. **Never auto-submit** rental applications or payments
6. **Save interesting listings** to memory for future comparison
7. **Recall previous searches** when user returns to apartment hunting
8. **Disclose mock data** clearly — never present mock listings as real
9. **Respect user budget** — don't show listings above stated maximum unless asked
10. **Include commute estimates** whenever workplace is known
11. **Batch API calls** — use pipe-delimited origins for Distance Matrix (max 10 per request)
12. **Log searches, never credentials** — never log API keys or user personal info
13. **Fall back gracefully** — if API fails, try browser; if browser fails, offer mock mode
14. **Cite sources** — always include the listing URL so user can verify independently

## Output Format

When your bash command finds results, end output with CARDS_JSON: followed by a JSON array. Cards auto-render on the user's phone — no need to call create_card separately.

CARDS_JSON:[{"type":"house","title":"1BR Mission $2,200","metadata":{"address":"123 Valencia St","rent":"$2,200","bedrooms":"1","area":"650 sqft"},"actions":["Schedule Tour","Save","Watch Price"]}]
