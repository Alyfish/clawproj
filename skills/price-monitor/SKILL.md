---
name: price-monitor
description: Monitor prices, listings, or odds for changes. Set up alerts for price drops, new listings, or line movements.
tools: [bash_execute, save_memory, search_memory, create_card, schedule]
approval_actions: []
version: "2.0.0"
author: ClawBot
tags: [monitoring, alerts, watchlist, price-tracking]
---

# Price Monitor

## Search Strategy (v2.1 — bash-first)

When checking a watched item, ALWAYS search via SearXNG first:

### Step 1: Search current price (bash, ~2 seconds)
```bash
curl -s "http://searxng:8080/search?q=current+price+Delta+NYC+LAX+flight&format=json" \
  | jq '.results[:5] | .[] | {title, url, snippet}' \
  > /workspace/data/price-check.json
```

### Step 2: Extract price from results
```bash
jq -r '.[] | .snippet' /workspace/data/price-check.json | grep -oP '\$[\d,]+(\.\d{2})?'
```

### Step 3: Deep dive (browser, ONLY if needed)
Only open the browser to:
- Verify an exact price on the source page
- Check if a listing has been removed or updated
- Confirm availability before alerting the user

DO NOT navigate to source sites and browse manually for price checks. SearXNG gives you the data faster.

### Step 4: Compare & alert
- Compare new price to saved baseline in memory
- If threshold met (e.g., price drop > $20), alert the user
- Update the saved price in memory for the next check

> **Execution preference:** Use bash_execute with curl/jq over web_search/http_request for composable, single-call execution.

## Context

This is a **meta-skill** — it does not search for flights, apartments, or odds on its own. It monitors things already found by other skills (`flight-search`, `apartment-search`, `betting-odds`) and alerts the user when something changes.

Think of it as a watchlist manager. Other skills find results; this skill watches them over time.

### Triggers

Activate this skill when the user says:
- "Watch this flight" / "Monitor that price"
- "Alert me if it drops below $X"
- "Track this listing" / "Notify me if new listings appear"
- "Watch this line" / "Alert me if the spread moves"
- "Check my watches" / "Any updates?"
- "What are you watching?" / "Show my alerts"
- "Stop watching" / "Cancel that alert"

---

## Watch Types

### price_watch

**Purpose:** Monitor a price for drops (or increases).

**Works with:** `flight-search`, `apartment-search`, any result that has a price.

**Memory storage:**

```
Tool: save_memory
{
  "key": "watch-price-sfo-lhr-20260315",
  "content": "# Price Watch: SFO → LHR Flight\n\n## Config\n- type: price_watch\n- source_skill: flight-search\n- baseline_price: 489.00\n- currency: USD\n- alert_threshold_amount: 50\n- alert_threshold_percent: 10\n- check_interval: daily\n- created_at: 2026-03-01T15:30:00Z\n- last_checked: 2026-03-01T15:30:00Z\n\n## Search Params\n- origin: SFO\n- destination: LHR\n- date: 2026-03-15\n- adults: 1\n- class: ECONOMY\n\n## Price History\n- 2026-03-01: $489 (BA 286, baseline)",
  "tags": ["active-watch", "price", "flights"]
}
```

**WatchlistItem mapping** (for iOS `WatchlistView`):

```json
{
  "id": "watch-price-sfo-lhr-20260315",
  "taskId": "task-current",
  "type": "price_watch",
  "description": "SFO → LHR under $439 (currently $489)",
  "filters": {
    "origin": "SFO",
    "destination": "LHR",
    "date": "2026-03-15",
    "baseline": "489",
    "threshold": "439"
  },
  "interval": "daily_morning",
  "lastChecked": "2026-03-01T15:30:00Z",
  "active": true
}
```

### new_listing

**Purpose:** Monitor for new apartment or rental listings matching criteria.

**Works with:** `apartment-search`

**Memory storage:**

```
Tool: save_memory
{
  "key": "watch-listing-austin-2br-2000",
  "content": "# Listing Watch: Austin 2BR under $2,000\n\n## Config\n- type: new_listing\n- source_skill: apartment-search\n- check_interval: daily\n- created_at: 2026-03-01T10:00:00Z\n- last_checked: 2026-03-01T10:00:00Z\n\n## Search Params\n- city: Austin, TX\n- bedrooms: 2\n- max_price: 2000\n- pet_policy: cats\n\n## Known Listing IDs\n- zpid-12345 (412 Chicon St, $1,750)\n- zpid-67890 (1800 E Riverside, $1,650)\n- zpid-11111 (900 E 5th St, $1,900)",
  "tags": ["active-watch", "listing", "apartments", "austin"]
}
```

**WatchlistItem mapping:**

```json
{
  "id": "watch-listing-austin-2br-2000",
  "taskId": "task-current",
  "type": "new_listing",
  "description": "New 2BR apartments in Austin under $2,000",
  "filters": {
    "city": "Austin, TX",
    "bedrooms": "2",
    "maxPrice": "2000",
    "petPolicy": "cats",
    "knownListings": "3"
  },
  "interval": "daily_morning",
  "lastChecked": "2026-03-01T10:00:00Z",
  "active": true
}
```

### line_movement

**Purpose:** Monitor betting lines for significant movements.

**Works with:** `betting-odds`

**Memory storage:**

```
Tool: save_memory
{
  "key": "watch-line-nba-lakers-celtics-20260305",
  "content": "# Line Watch: Lakers vs Celtics (Mar 5)\n\n## Config\n- type: line_movement\n- source_skill: betting-odds\n- sport: basketball_nba\n- event_id: nba-lakers-celtics-20260305\n- check_interval: hourly\n- created_at: 2026-03-01T12:00:00Z\n- last_checked: 2026-03-01T12:00:00Z\n\n## Alert Thresholds\n- spread: 1.0 points\n- moneyline: 15 cents\n- total: 1.5 points\n\n## Baseline Odds (DraftKings)\n- spread: Celtics -5.5\n- moneyline: Celtics -220 / Lakers +185\n- total: O/U 224.5\n- captured_at: 2026-03-01T12:00:00Z\n\n## Line History\n- 2026-03-01 12:00: Celtics -5.5, O/U 224.5",
  "tags": ["active-watch", "odds", "nba", "celtics", "lakers"]
}
```

**WatchlistItem mapping:**

```json
{
  "id": "watch-line-nba-lakers-celtics-20260305",
  "taskId": "task-current",
  "type": "line_movement",
  "description": "Lakers vs Celtics line (Mar 5) — Celtics -5.5",
  "filters": {
    "sport": "basketball_nba",
    "event": "Lakers vs Celtics",
    "date": "2026-03-05",
    "spread": "Celtics -5.5",
    "total": "O/U 224.5"
  },
  "interval": "every_hour",
  "lastChecked": "2026-03-01T12:00:00Z",
  "active": true
}
```

---

## Creating a Watch

When the user asks to watch/monitor something:

### Step 1: Identify What to Watch

Determine from conversation context:
- **What type?** `price_watch`, `new_listing`, or `line_movement`
- **Which skill produced the result?** flight-search, apartment-search, betting-odds
- **What are the search params?** Extract from the original search that found the result
- **What is the baseline value?** Current price, listing set, or odds line

If context is ambiguous, ask the user to clarify.

### Step 2: Set Alert Threshold

Use defaults or ask the user:

| Watch Type | Default Threshold | User Override |
|------------|------------------|---------------|
| `price_watch` | Drop > $50 OR > 10% | "Alert me if it drops below $450" |
| `new_listing` | Any new listing ID | "Only alert for pet-friendly" |
| `line_movement` | Spread > 1pt, ML > 15¢, Total > 1.5pt | "Alert if spread hits -3" |

### Step 3: Generate Watch ID

Create a unique, descriptive key:
- `watch-price-{origin}-{dest}-{date}` — flights
- `watch-price-{city}-{type}-{id}` — apartments
- `watch-listing-{city}-{beds}br-{maxprice}` — listing monitors
- `watch-line-{sport}-{team1}-{team2}-{date}` — odds

Use lowercase, hyphens only. No special characters.

### Step 4: Save to Memory

Use `save_memory` with the appropriate format from Watch Types above.

**Required tags:** Always include `"active-watch"` as the first tag, plus category and specifics.

### Step 5: Confirm to User

```
✓ Watching {description}.
  Threshold: {threshold description}
  Check frequency: {interval}
  Say "check my watches" anytime to re-check.
```

---

## Checking Watches

When the user says "check my watches" or "any updates?":

### Step 1: Find Active Watches

```
Tool: search_memory
{
  "query": "active-watch",
  "limit": 20
}
```

Parse results to find all entries with `"active-watch"` tag.

### Step 2: Process Each Watch

For each active watch, use bash-first (curl/jq) for data fetching and structured tools (create_card, save_memory) for outputs that iOS needs.

**price_watch:**
1. **Search (bash):**
   ```
   bash_execute: curl -s 'http://searxng:8080/search?q={item}+price+buy&format=json' | jq '.results[:5]' > /workspace/data/price-search-{watch_id}.json
   ```
2. **Extract prices (bash):**
   For each URL from search results:
   ```
   bash_execute: curl -sL "{url}" | grep -oP '\$[\d,]+\.?\d{0,2}' | head -5
   ```
   If curl returns nothing useful → fall back to browser tool for that URL.
3. **Compare and alert (structured tool):**
   Compare extracted prices to `baseline_price` from watch config.
   If threshold exceeded → `create_card` with price drop data (MUST use create_card — iOS needs typed data).
4. **Update memory:**
   `save_memory` with updated price history and `last_checked`.

**new_listing:**
1. **Search (bash):**
   ```
   bash_execute: curl -s 'http://searxng:8080/search?q={city}+{beds}BR+apartment+rent&format=json' | jq '.results[:10]' > /workspace/data/listing-search-{watch_id}.json
   ```
2. **Extract listings (bash):**
   ```
   bash_execute: jq -r '.[].url' /workspace/data/listing-search-{watch_id}.json | while read url; do curl -sL "$url" | grep -i 'listing\|available\|bedroom' | head -3; done
   ```
3. Compare IDs to known set, alert on new ones via `create_card`.
4. Update `last_checked` via `save_memory`.

**line_movement:**
1. **Fetch odds (bash):**
   ```
   bash_execute: curl -s 'http://searxng:8080/search?q={team1}+vs+{team2}+odds+spread&format=json' | jq '.results[:5]' > /workspace/data/odds-{watch_id}.json
   ```
2. **Extract lines (bash):**
   For each URL: `curl -sL` and grep for spread/odds patterns.
3. Compare to baseline, alert via `create_card` if threshold exceeded.
4. Update line history via `save_memory`.

### Step 3: Update Memory

After checking, update the watch entry with:
- New `last_checked` timestamp
- Updated price/line history
- Updated `known_listing_ids` (for new_listing)
- Do NOT update `baseline_price` — always compare to original baseline

```
Tool: save_memory
{
  "key": "watch-price-sfo-lhr-20260315",
  "content": "...updated content with new history entry and last_checked...",
  "tags": ["active-watch", "price", "flights"]
}
```

### Step 4: Report Results

```
Checked 3 watches. 1 alert triggered.

📉 SFO → LHR: Price dropped to $412 (was $489, down $77 / 15.7%)
  → Would you like to see updated flight results?

✅ Austin 2BR: No new listings since last check (3 known)
✅ Lakers vs Celtics: Line unchanged at Celtics -5.5
```

### Step 5: Monitor Script (bash + structured)

For recurring watches, generate a self-contained monitoring script:

```
bash_execute: cat > /workspace/scripts/monitor-{watch_id}.sh << 'EOF'
#!/bin/bash
# Auto-generated by price-monitor skill
SEARCH_URL="http://searxng:8080/search?q={query}&format=json"
OUTPUT="/workspace/data/monitor-{watch_id}-latest.json"
curl -s "$SEARCH_URL" | jq '.results[:5]' > "$OUTPUT"
# Extract and compare prices/listings/odds...
EOF
chmod +x /workspace/scripts/monitor-{watch_id}.sh
```

Register with the `schedule` tool for cron execution. The script handles data fetching; the agent interprets results and creates alerts via structured tools on the next scheduled run.

---

## Alert Output

When a threshold is exceeded, create a `MonitoringAlert` (aligned to `shared/types/monitoring.ts`):

```json
{
  "id": "alert-{timestamp}",
  "watchlistItemId": "watch-price-sfo-lhr-20260315",
  "message": "Price dropped to $412 on British Airways BA 286",
  "data": {
    "previous_value": "489",
    "current_value": "412",
    "change": "-77",
    "change_percent": "-15.7%",
    "airline": "British Airways",
    "flight": "BA 286",
    "source_skill": "flight-search",
    "action_suggestion": "Check latest flights"
  },
  "timestamp": "2026-03-02T09:00:00Z"
}
```

**iOS alert type auto-detection** (from `AlertCardView.swift`):
- Include "price" or "drop" in message → green down-arrow icon
- Include "listing" or "new" in message → blue house icon
- Include "line" or "moved" in message → orange chart icon

Use these keywords deliberately in alert messages so iOS renders the correct icon.

### Alert Message Templates

**price_watch:**
- Drop: `"Price dropped to ${current} on {carrier} {flight} (was ${baseline}, down ${change})"`
- Rise: `"Price increased to ${current} (was ${baseline}, up ${change}) — no action needed"`

**new_listing:**
- `"New listing: {beds}BR at {address} for ${price}/mo ({source})"`
- Multiple: `"{count} new listings found matching your Austin 2BR search"`

**line_movement:**
- Spread: `"Line moved: {team} spread shifted from {old} to {new} ({direction} {delta}pts)"`
- Total: `"Total moved from {old} to {new} ({direction} {delta}pts)"`
- ML: `"Moneyline moved: {team} from {old} to {new}"`

---

## Alert Thresholds

### Defaults

| Watch Type | Metric | Default Threshold |
|------------|--------|-------------------|
| `price_watch` | Dollar drop | > $50 |
| `price_watch` | Percent drop | > 10% |
| `new_listing` | New listings | Any new listing ID |
| `line_movement` | Spread | > 1.0 points |
| `line_movement` | Moneyline | > 15 cents |
| `line_movement` | Total (O/U) | > 1.5 points |

For `price_watch`, trigger an alert if EITHER the dollar OR percent threshold is exceeded.

### User Overrides

Users can set custom thresholds:
- "Alert me only if it drops below $400" → set `alert_threshold_amount: 89` (489 - 400)
- "Alert me if spread moves more than 2 points" → set `spread: 2.0`
- "Only alert for pet-friendly listings" → add filter to `search_params`

Store the custom threshold in the watch config. Always prefer user-specified thresholds over defaults.

---

## Deactivating a Watch

When the user says "stop watching" or "cancel alert":

### Step 1: Identify Which Watch

If the user is specific ("stop watching that flight"), match to the watch by description.

If ambiguous, list active watches and ask which to deactivate.

### Step 2: Remove the Watch

**Option A — Delete entry:**
```
Tool: save_memory
{
  "key": "watch-price-sfo-lhr-20260315",
  "content": "",
  "tags": []
}
```
Or use the memory delete operation if available.

**Option B — Remove active-watch tag** (preserves history):
Update the entry, removing `"active-watch"` from tags and replacing with `"inactive-watch"`:
```
Tool: save_memory
{
  "key": "watch-price-sfo-lhr-20260315",
  "content": "...same content with status: inactive appended...",
  "tags": ["inactive-watch", "price", "flights"]
}
```

Prefer Option B — it preserves the price/line history for reference.

### Step 3: Confirm

```
✓ Stopped monitoring SFO → LHR flight prices.
  Final baseline: $489 → Last checked: $412 (saved $77).
  History preserved — say "show my watch history" to review.
```

---

## Listing Active Watches

When the user says "what are you watching?" or "show my alerts":

### Step 1: Query Memory

```
Tool: search_memory
{
  "query": "active-watch",
  "limit": 20
}
```

### Step 2: Display Summary

```
📋 Active Watches (3)

1. ✈️  SFO → LHR Flight Price
   Baseline: $489 | Threshold: drop > $50 or 10%
   Last checked: 2 hours ago | Interval: daily

2. 🏠  Austin 2BR Apartments under $2,000
   Tracking: 3 known listings | Alert: any new listing
   Last checked: 1 day ago | Interval: daily

3. 🏀  Lakers vs Celtics (Mar 5) Line
   Baseline: Celtics -5.5, O/U 224.5
   Last checked: 45 min ago | Interval: hourly

Say "check my watches" to re-check all now.
Say "stop watching [name]" to deactivate one.
```

---

## Cross-Skill Integration

When another skill runs and the user has active watches related to it:

**flight-search runs:** Check if user has any `price_watch` watches for the same route. If so, mention: "You have an active watch for SFO → LHR. Current best: $412 (down from $489 baseline)."

**apartment-search runs:** Check if user has any `new_listing` watches for the same city/criteria. If so, compare results to known listing IDs and flag new ones.

**betting-odds runs:** Check if user has any `line_movement` watches for the same event. If so, compare current odds to baseline and flag movements.

This cross-referencing happens naturally when the agent checks memory during other skill executions.

---

## Important Notes

1. **Scheduling integration.** When the user says "watch this" or "monitor that", use the `schedule` tool to register a recurring check. This skill handles the checking logic; the scheduler handles timing. See [Scheduling Integration](#scheduling-integration) below.
2. **Watches persist via memory** across conversations. The user can return days later and their watches will still be active.
3. **Keep watch configs lean.** Store search params and baseline values, not full API responses. The check flow re-fetches current data each time.
4. **Never update baseline.** The baseline is what the user originally saw. Always compare current values to the original baseline. If the user says "reset my baseline" then update it explicitly.
5. **Log changes, not values.** The Price History / Line History sections log directional changes. Don't log identical values on consecutive checks.

---

## Scheduling Integration

When creating a watch (Step 5), also register it with the scheduler so checks run automatically:

```
Tool: schedule
{
  "action": "create_watch",
  "description": "SFO → LHR flight price monitor",
  "interval": "daily_morning",
  "check_instructions": "Search SFO→LHR flights for 2026-03-15, 1 adult, economy. Compare best price to $489 baseline. Alert if drop exceeds $50 or 10%.",
  "skill_name": "price-monitor",
  "payload": {
    "watch_key": "watch-price-sfo-lhr-20260315",
    "watch_type": "price_watch",
    "source_skill": "flight-search"
  }
}
```

**How it works:**

- **This skill** owns the checking logic: fetching current data, comparing to baselines, generating alerts, updating memory.
- **The scheduler** owns timing: it fires at the configured `interval` and invokes the agent with the `check_instructions` and the previous result.
- When a scheduled check fires, the agent receives `check_instructions` plus any prior result from the last run. Execute the instructions (re-search, compare, threshold check) and report findings via the normal alert flow.
- The user can still say "check my watches" for an immediate manual check at any time.

When deactivating a watch, also cancel the corresponding schedule entry.

---

## Example Interactions

### Flight Price Watch

**User:** "Watch that SFO to London flight — alert me if it drops below $450"

**Agent:**
> ✓ Watching SFO → LHR flights (currently $489 on BA 286).
> I'll alert you if the price drops below $450 (threshold: -$39).
> Check frequency: daily. Say "check my watches" anytime to re-check.

*[saves watch to memory with `active-watch` tag]*

**User (next day):** "Check my watches"

**Agent:**
> Checked 1 watch. 1 alert triggered!
>
> 📉 **SFO → LHR: Price dropped to $412** (was $489, down $77 / 15.7%)
> British Airways BA 286, nonstop, departs 3:40 PM
> This is below your $450 threshold.
>
> Want to see updated flight results? Or book this fare?

### New Listing Watch

**User:** "Watch for new 2BR apartments in Austin under $2,000"

**Agent:**
> ✓ Watching for new 2BR listings in Austin, TX under $2,000/mo.
> Currently tracking 3 known listings. I'll alert you when new ones appear.
> Check frequency: daily. Say "check my watches" anytime.

**User (3 days later):** "Any new apartments?"

**Agent:**
> Checked 1 watch. 2 new listings found!
>
> 🏠 **New: 2BR/1BA at 505 E 7th St** — $1,850/mo, 920 sqft
> Listed today on Zillow | 0 red flags | 12 min commute
>
> 🏠 **New: 2BR/2BA at 2200 S Congress** — $1,950/mo, 1,050 sqft
> Listed yesterday on Apartments.com | 1 caution flag (personal email) | 20 min commute
>
> Now tracking 5 total listings. Want to see details or compare?

### Line Movement Watch

**User:** "Watch the Celtics-Lakers line for tonight"

**Agent:**
> ✓ Watching Lakers vs Celtics (Mar 5) line movement.
> Baseline: Celtics -5.5 | O/U 224.5 (DraftKings)
> Alert thresholds: spread ±1pt, ML ±15¢, total ±1.5pts
> Check frequency: hourly. Say "check my watches" anytime.

**User (4 hours later):** "Check my watches"

**Agent:**
> Checked 1 watch. 1 alert triggered!
>
> 📊 **Lakers vs Celtics: Line moved**
> Spread: Celtics -5.5 → **Celtics -3.5** (moved 2pts toward Lakers)
> Total: 224.5 → 226.0 (up 1.5pts)
> Moneyline: Celtics -220/+185 → Celtics -175/+150
>
> Significant movement toward the Lakers. Possible injury news or sharp action.
> Want me to check for injury updates?

---

## Rules

1. **Always confirm watch creation** with a summary of what's being watched, the threshold, and the check interval
2. **Never create a watch without clear baseline values** — if the user says "watch flights" without a prior search, run the search first
3. **Update `last_checked`** on every check, even if no alert is triggered
4. **Keep watch configs lean** — store params + baseline, not full API responses
5. **Preserve history** — append to Price History / Line History sections, don't overwrite
6. **Tag consistently** — always use `"active-watch"` as the first tag for active monitors
7. **Use alert-friendly keywords** — include "price"/"drop", "listing"/"new", or "line"/"moved" in alert messages so iOS renders the correct icon
8. **Don't spam alerts** — if the same threshold was already triggered and the user hasn't acknowledged it, don't re-alert on the next check (note it as "still below threshold" instead)
9. **Cross-reference** — when other skills run, check for related watches and mention relevant updates
10. **Respect deactivation** — when a watch is deactivated, never re-activate it automatically

## Output Format

When your bash command finds results, end output with CARDS_JSON: followed by a JSON array. Cards auto-render on the user's phone — no need to call create_card separately.

CARDS_JSON:[{"type":"generic","title":"Jordan 11 — $75","metadata":{"source":"Foot Locker","price":"$75","url":"https://footlocker.com"},"actions":["Watch Price","Open","Share"]}]
