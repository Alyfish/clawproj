---
name: betting-odds
description: >-
  Get sports betting odds, track line movement, build bet slips, and generate
  game recaps. Use whenever the user mentions odds, betting lines, spreads,
  parlays, moneyline, who's favored, over/under, point spread, totals, prop
  bets, value bet, line movement, best lines, sportsbook comparison, implied
  probability, vig, juice, or any sports wagering topic — even if they don't
  explicitly say "betting."
tools: [http_request, browser, code_execution, create_card, save_memory]
approval_actions: [pay]
version: 1.0.0
author: clawbot
tags: [sports, betting, odds]
---

# Betting Odds Research

Sports betting RESEARCH assistant — fetch live odds, compare lines across
bookmakers, track movement, and calculate parlay payouts. Information only.

**Disclaimer:** For informational purposes only. Gambling involves risk.
Never claim to predict outcomes or guarantee returns.

## Context

You help the user research sports betting lines. Typical requests:

- "What are the odds for tonight's NBA games?"
- "Who's favored in the Chiefs game?"
- "Build me a 3-leg parlay with the Lakers, Celtics, and over on Nuggets"
- "Track the line on Cowboys -3.5 and alert me if it moves"
- "Compare moneyline prices across books for the UFC main event"
- "What's the implied probability on Dodgers -150?"

**Trigger phrases:** odds, betting, spread, parlay, moneyline, ML, over/under,
O/U, totals, prop bet, player prop, line movement, best line, sharp money,
public money, vig, juice, value bet, EV, expected value, sportsbook, DraftKings,
FanDuel, BetMGM, who's favored, point spread, handicap, accumulator, teaser,
round robin, futures, outrights.

## Authentication

**The Odds API** (primary data source):
- Credential key: `odds_api`
- Env var: `CLAWBOT_CRED_ODDS_API`
- Applied as query parameter: `?apiKey={key}`
- Free tier: 500 requests/month
- If credential is missing, try **Browser Mode** first (ESPN/OddsShark scraping for real data)
- If browser also fails, operate in **Mock Mode** (see below)

## API: The Odds API (V4)

Base URL: `https://api.the-odds-api.com`

All responses include quota headers:
- `x-requests-remaining` — credits left until reset
- `x-requests-used` — credits consumed since last reset
- `x-requests-last` — cost of the most recent call

Always log remaining quota after each call. Warn the user if below 50.

### List Sports (free)

`GET /v4/sports/?apiKey={key}` — Returns in-season sports. Free (0 credits).
Optional `all=true` for out-of-season. Response: array of `{ key, group, title, active }`.

### List Events (free)

`GET /v4/sports/{sport}/events?apiKey={key}` — Returns upcoming events WITHOUT
odds. Free (0 credits). Use to get event IDs before fetching single-event odds.
Optional filters: `commenceTimeFrom`, `commenceTimeTo` (ISO 8601).

### Get Odds (bulk)

```
GET /v4/sports/{sport}/odds/?apiKey={key}&regions={regions}&markets={markets}
```

Returns odds for all upcoming/live events in a sport.

| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `sport` | yes | — | Sport key, or `upcoming` for next 8 across all sports |
| `regions` | yes | — | Comma-separated: `us`, `us2`, `uk`, `au`, `eu` |
| `markets` | no | `h2h` | Comma-separated: `h2h`, `spreads`, `totals`, `outrights` |
| `oddsFormat` | no | `decimal` | `american` or `decimal` |
| `dateFormat` | no | `iso` | `iso` or `unix` |
| `bookmakers` | no | — | Comma-separated bookmaker keys (overrides regions) |
| `commenceTimeFrom` | no | — | ISO 8601 filter |
| `commenceTimeTo` | no | — | ISO 8601 filter |

**Cost:** 1 credit per region per market.
- 2 markets + 1 region = 2 credits
- 1 market + 3 regions = 3 credits
- Empty response = 0 credits

**Always use `oddsFormat=american`** for US users unless they ask for decimal.
**Always use `regions=us`** as default. Add `us2` only if user wants more books.

### Get Event Odds (single event + player props)

```
GET /v4/sports/{sport}/events/{eventId}/odds?apiKey={key}&regions={regions}&markets={markets}
```

Same params as bulk odds. Use this endpoint when:
- User asks about a specific game
- User wants player props (only available here)
- User wants alternate spreads/totals

**Cost:** 1 credit per region per market (only charged for markets returned).

### Get Scores

```
GET /v4/sports/{sport}/scores/?apiKey={key}
```

Returns live scores and recently completed games.

| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `daysFrom` | no | — | 1-3, include completed games from past N days |

**Cost:** 1 credit (2 if `daysFrom` is set).

Response includes `completed: true/false` and `scores` array with `name` + `score`.

### Response Structure

All odds endpoints return this shape:

```json
[
  {
    "id": "abc123def456",
    "sport_key": "basketball_nba",
    "sport_title": "NBA",
    "commence_time": "2025-01-15T00:30:00Z",
    "home_team": "Los Angeles Lakers",
    "away_team": "Boston Celtics",
    "bookmakers": [
      {
        "key": "fanduel",
        "title": "FanDuel",
        "last_update": "2025-01-14T22:00:00Z",
        "markets": [
          {
            "key": "h2h",
            "last_update": "2025-01-14T22:00:00Z",
            "outcomes": [
              { "name": "Los Angeles Lakers", "price": -150 },
              { "name": "Boston Celtics", "price": 130 }
            ]
          },
          {
            "key": "spreads",
            "outcomes": [
              { "name": "Los Angeles Lakers", "price": -110, "point": -3.5 },
              { "name": "Boston Celtics", "price": -110, "point": 3.5 }
            ]
          },
          {
            "key": "totals",
            "outcomes": [
              { "name": "Over", "price": -110, "point": 224.5 },
              { "name": "Under", "price": -110, "point": 224.5 }
            ]
          }
        ]
      }
    ]
  }
]
```

Key notes:
- `price` is in the requested `oddsFormat` (American or decimal)
- `point` appears for spreads and totals (the line number)
- Spreads: negative point = favorite, positive = underdog
- Totals: Over/Under with the same `point` value
- `last_update` on bookmaker AND market level — check staleness

### Sport Keys

Common sport keys (use `/v4/sports` endpoint for the full list):
- `americanfootball_nfl`, `americanfootball_ncaaf`
- `basketball_nba`, `basketball_ncaab`, `basketball_wnba`
- `baseball_mlb`
- `icehockey_nhl`
- `soccer_epl`, `soccer_usa_mls`, `soccer_spain_la_liga`, `soccer_uefa_champs_league`
- `mma_mixed_martial_arts`

When the user says a team or league name, map it to the correct sport key.
If ambiguous, call `/v4/sports` first to check what's in season.

### Market Keys

**Featured markets** (available on bulk endpoint):
- `h2h` — Moneyline / head-to-head
- `spreads` — Point spread / handicap
- `totals` — Over/Under
- `outrights` — Futures / season winners

**Additional markets** (single-event endpoint only):
- `alternate_spreads` — All available spread lines
- `alternate_totals` — All available total lines
- `team_totals` — Team-specific over/under
- `btts` — Both teams to score (soccer)
- `draw_no_bet` — Exclude draw result (soccer)
- `h2h_h1`, `spreads_h1`, `totals_h1` — First half lines
- `h2h_q1` through `h2h_q4` — Quarter lines

**Player props** (single-event endpoint, US sports):
- NFL: `player_pass_yds`, `player_rush_yds`, `player_anytime_td`, `player_receptions`
- NBA: `player_points`, `player_rebounds`, `player_assists`, `player_threes`
- MLB: `batter_home_runs`, `batter_hits`, `pitcher_strikeouts`
- NHL: `player_points`, `player_goals`, `player_shots_on_goal`

### Cost Optimization

Use free endpoints (`/sports`, `/events`) first. Request only needed markets.
Default `regions=us`. Fetch by sport, filter client-side. Empty responses = 0 credits.

## Odds Conversion Formulas

Use `code_execution` for all math. These are the exact formulas:

### American to Decimal
```python
def american_to_decimal(american: int) -> float:
    if american > 0:
        return (american / 100) + 1      # +130 → 2.30
    else:
        return (100 / abs(american)) + 1  # -150 → 1.667
```

### Decimal to Implied Probability
```python
def decimal_to_implied(decimal_odds: float) -> float:
    return 1 / decimal_odds  # 2.30 → 0.4348 (43.5%)
```

### American to Implied Probability
```python
def american_to_implied(american: int) -> float:
    if american < 0:
        return abs(american) / (abs(american) + 100)  # -150 → 0.600
    else:
        return 100 / (american + 100)                  # +130 → 0.435
```

### Remove Vig (True Probability)
```python
def remove_vig(probabilities: list[float]) -> list[float]:
    overround = sum(probabilities)           # e.g. 1.035
    return [p / overround for p in probabilities]
```

### Display Format
- Always show American odds with sign: +130, -150
- Show implied probability as percentage: 43.5%
- Show decimal to 2 places: 2.30
- When comparing books, show the best price in bold

## Value Assessment

Compare implied probability across bookmakers to find value:

1. **Collect** implied probabilities for the same outcome across all books
2. **Calculate** the consensus (average) implied probability
3. **Find** the best available odds (lowest implied probability = best price)
4. **Flag discrepancies** > 3 percentage points between best and worst book
5. **Calculate expected value:**
   ```
   EV = (true_prob x potential_profit) - ((1 - true_prob) x stake)
   ```
   - Positive EV = potential value (flag to user)
   - Use vig-removed probability as `true_prob`

Value rating for PickCard:
- `"high"` — EV > +5% AND best odds diverge > 5% from consensus
- `"medium"` — EV > +2% OR best odds diverge > 3% from consensus
- `"low"` — no significant edge detected

When flagging value, always caveat: "This is a mathematical observation based
on line discrepancies, not a prediction."

## Line Movement Tracking

When the user asks to "watch" or "track" a line:

### Save Snapshot
Use `save_memory` with:
- **key:** `odds-{sport_key}-{eventId}-{timestamp}`
- **content:** JSON with event_id, sport, teams, commence_time, snapshot_time,
  and odds object keyed by bookmaker containing market prices
- **tags:** `["active-watch", "odds", "{sport_key}"]`

### Detect Movement
On re-check, search memory for previous snapshots and compare:

| Market | Significant Movement |
|--------|---------------------|
| Spread | Moved > 1 point |
| Moneyline | Moved > 15 cents (e.g., -150 → -165) |
| Total | Moved > 1.5 points |

Report movement as: "Opened -2.5, now -3.5 (moved 1 point toward Lakers)"

Include direction context:
- Line moving toward favorite = sharp money or injury news
- Line moving toward underdog = public money or value correction

### Cleanup
Old snapshots (event already commenced) can be left in memory — they serve
as historical records. Do NOT delete them automatically.

## Bet Slip Math

### Single Bet
- Payout = stake x decimal_odds
- Profit = payout - stake

### Parlay (Accumulator)
```python
def parlay_odds(decimal_odds_list: list[float]) -> float:
    result = 1.0
    for odds in decimal_odds_list:
        result *= odds
    return result

# Example: 3-leg at 2.0, 1.8, 2.5
# Combined = 2.0 * 1.8 * 2.5 = 9.0
# $10 stake pays $90 ($80 profit)
```

### Round Robin
All possible parlay combinations of N picks taken K at a time:
```python
from itertools import combinations

def round_robin(picks: list, parlay_size: int, stake: float):
    combos = list(combinations(picks, parlay_size))
    total_cost = len(combos) * stake
    # Calculate each sub-parlay individually
    return combos, total_cost
```

### Teaser (NFL/NBA only)
- NFL: 6, 6.5, or 7 point teaser
- NBA: 4, 4.5, or 5 point teaser
- Adjust each spread by teaser points, then calculate as parlay
- All legs must win (no pushes in standard teasers)

Always show:
- Total cost (number of bets x stake)
- Maximum potential payout
- Individual leg breakdown
- Implied probability of hitting all legs

## Card Output (PickCard)

Use `create_card` tool. The card MUST conform to the `PickCard` interface
defined in `shared/types/cards.ts`.

### Required Fields

```json
{
  "type": "pick",
  "id": "pick-{eventId}-{market}-{timestamp}",
  "title": "Lakers vs Celtics",
  "subtitle": "NBA | Tonight 7:30 PM ET",
  "createdAt": "2025-01-14T22:00:00Z",
  "matchup": {
    "home": "Los Angeles Lakers",
    "away": "Boston Celtics"
  },
  "sport": "basketball",
  "league": "NBA",
  "line": "Lakers -3.5 (-110)",
  "impliedOdds": 0.524,
  "recentMovement": "Opened -2.5, now -3.5",
  "notes": "Best line at FanDuel (-108). DraftKings has -110.",
  "valueRating": "medium",
  "metadata": {
    "event_id": "abc123",
    "sport_key": "basketball_nba",
    "commence_time": "2025-01-15T00:30:00Z",
    "market": "spreads",
    "best_book": "FanDuel",
    "best_price": -108,
    "worst_book": "BetMGM",
    "worst_price": -115,
    "ev_percent": 2.3,
    "consensus_implied": 0.535,
    "bookmaker_count": 4
  },
  "ranking": {
    "label": "Best Value",
    "reason": "+2.3% EV vs consensus"
  },
  "source": "The Odds API"
}
```

### Field Mapping

| PickCard field | Source |
|----------------|--------|
| `matchup.home` | API `home_team` |
| `matchup.away` | API `away_team` |
| `sport` | Derive from `sport_key` (e.g., `basketball_nba` → `"basketball"`) |
| `league` | Derive from `sport_key` (e.g., `basketball_nba` → `"NBA"`) |
| `line` | Format: `"{team} {point} ({price})"` for spreads, `"{team} ({price})"` for h2h |
| `impliedOdds` | Best available implied probability (0-1 scale) |
| `recentMovement` | From memory comparison, or `"No movement tracked"` |
| `notes` | Best/worst book comparison, key context |
| `valueRating` | `"high"`, `"medium"`, or `"low"` per value assessment rules |

### Multiple Cards

When showing odds for multiple games:
- Create one PickCard per game
- If user asks about specific markets (spread AND total), create one card per
  market per game
- For parlays, create individual cards for each leg PLUS a summary card with
  combined odds in the `line` field

## Browser Mode (Fallback — No API Key Needed)

When `CLAWBOT_CRED_ODDS_API` is not set, use the `browser` tool to scrape real odds data from public sports sites. This provides real data without any API key.

### Site Priority

1. **ESPN** — Most reliable, minimal anti-bot, covers major US sports
2. **OddsShark** — Good fallback, more detailed odds comparison

### Sport Key to ESPN URL

| Sport Key / User Request | ESPN URL |
|--------------------------|----------|
| `basketball_nba` / "NBA" | `https://www.espn.com/nba/odds` |
| `americanfootball_nfl` / "NFL" | `https://www.espn.com/nfl/odds` |
| `baseball_mlb` / "MLB" | `https://www.espn.com/mlb/odds` |
| `icehockey_nhl` / "NHL" | `https://www.espn.com/nhl/odds` |
| `americanfootball_ncaaf` / "NCAAF" | `https://www.espn.com/college-football/odds` |
| `basketball_ncaab` / "NCAAB" | `https://www.espn.com/mens-college-basketball/odds` |
| Soccer, MMA, other | Not available on ESPN — fall through to OddsShark or Mock Mode |

### Strategy: ESPN Odds

**Step 1: Navigate to sport odds page**

```
Tool: browser
{
  "action": "navigate",
  "params": {"url": "https://www.espn.com/nba/odds"}
}
```

**Step 2: Wait for odds content to load**

```
Tool: browser
{
  "action": "wait_for_selector",
  "params": {"selector": "table", "timeout": 10000}
}
```

**Step 3: Extract page content**

```
Tool: browser
{
  "action": "get_page_content",
  "params": {}
}
```

**Step 4: Parse odds from page text**

ESPN odds pages display in table format with columns for each sportsbook. Use `code_execution` to parse:

```python
Tool: code_execution
{
  "language": "python",
  "code": "import re, json\n\npage_text = '''<paste page content here>'''\n\nevents = []\nlines = [l.strip() for l in page_text.split('\\n') if l.strip()]\n\n# ESPN typically shows odds in blocks per game:\n# Team name lines, followed by odds (spread, ML, total) from each book\n# Look for patterns like: team names, +/- numbers, O/U numbers\n\nspread_pattern = r'([+-]\\d+\\.?\\d*)\\s*\\(([+-]\\d+)\\)'\nml_pattern = r'([+-]\\d{3,})'\ntotal_pattern = r'([OU])\\s*(\\d+\\.?\\d*)'\n\ncurrent_event = {}\nfor line in lines:\n    # Adapt parsing based on actual ESPN text structure\n    spreads = re.findall(spread_pattern, line)\n    mls = re.findall(ml_pattern, line)\n    totals = re.findall(total_pattern, line)\n    \n    if spreads:\n        spread_val, spread_price = spreads[0]\n        current_event.setdefault('odds', {})['spread'] = float(spread_val)\n        current_event['odds']['spread_price'] = int(spread_price)\n    if mls:\n        current_event.setdefault('odds', {})['moneyline'] = int(mls[0])\n    if totals:\n        current_event.setdefault('odds', {})['total'] = float(totals[0][1])\n        current_event['odds']['total_side'] = totals[0][0]\n\n# Output whatever structure was extracted\nprint(json.dumps(events[:15], indent=2))"
}
```

**IMPORTANT:** The parsing code above is a template. ESPN page format varies by sport and season. Always inspect the `get_page_content` output first and adapt the parsing accordingly. The LLM should reason about the actual text structure.

**Step 5: Scroll for more games (if needed)**

```
Tool: browser
{
  "action": "scroll",
  "params": {"direction": "down", "amount": 1500}
}
```

### Strategy: OddsShark (Fallback)

If ESPN fails or the sport isn't available on ESPN:

```
Tool: browser
{
  "action": "navigate",
  "params": {"url": "https://www.oddsshark.com/nba/odds"}
}
```

Follow the same `get_page_content` → `code_execution` pipeline. OddsShark URLs follow the pattern: `https://www.oddsshark.com/{sport}/odds`

### Card Mapping from Browser Results

Map parsed fields to PickCard format:

| Parsed Field | PickCard Field |
|-------------|---------------|
| home team / away team | `matchup.home` / `matchup.away` |
| sport | `sport` (derive from URL) |
| league | `league` (derive from URL) |
| spread value + price | `line` (format: "{team} {spread} ({price})") |
| moneyline | Alternative `line` format for h2h |
| implied probability | `impliedOdds` (calculate from best odds) |

Set `source` to `"ESPN (browser)"` or `"OddsShark (browser)"`.

Fields not available via browser scraping:
- `event_id` — generate synthetic ID from team names + date
- `recentMovement` — set to "No movement data (browser scrape)" unless previous snapshot exists in memory
- `metadata.ev_percent` — cannot calculate without multi-book vig-removed odds
- `metadata.bookmaker_count` — set based on how many books ESPN shows (typically 4-6)

### Browser Limitations

When using browser-scraped odds, these limitations apply:
- **No player props** — only main markets (spreads, moneylines, totals)
- **No event IDs** — cannot use for single-event deep dives
- **Fewer bookmakers** — ESPN shows 4-6 books vs API's 10+
- **No live score integration** — scores endpoint not available via scraping
- **No quota tracking** — no API quota to manage
- **Line movement** — compare to saved memory snapshots (same as API approach)

### Anti-Bot Handling

1. ESPN blocked → try OddsShark
2. OddsShark blocked → fall through to Mock Mode
3. Both blocked: tell user "Browser scraping is currently blocked. Showing simulated odds. Add The Odds API credential for live data: set `CLAWBOT_CRED_ODDS_API` env var."

### Browser Source Attribution

When presenting browser-scraped results, add:
> **Data via ESPN** — Showing odds from ESPN.com. For more bookmakers and player props, add The Odds API credential: set `CLAWBOT_CRED_ODDS_API` env var.


## Mock Mode

When `CLAWBOT_CRED_ODDS_API` is not set AND browser scraping has failed or is unavailable, generate realistic synthetic data.
Clearly indicate mock mode: add `"[MOCK DATA]"` prefix to card titles.

### Mock Data Rules

Generate 8-10 events with realistic characteristics:

**NBA mock spreads:** 1-12 points, home team favored ~55% of the time
**NFL mock spreads:** 1-14 points, home team favored ~57% of the time
**MLB mock moneylines:** -200 to +200 range
**Soccer mock:** Draw included in h2h at ~20% implied probability

Each event gets 3 bookmakers with slight variations:
- Base odds set randomly within realistic range
- Each book deviates 2-8 cents from base
- Totals: NBA ~215-235, NFL ~40-55, MLB ~7.5-10.5

Include at least one clear value discrepancy for demo:
- One event where FanDuel has -130 but others have -150+
- Flag this with `valueRating: "high"`

### Mock Events

Use the same response structure as the API (see Response Structure above).
Generate these matchups with 3 bookmakers each (FanDuel, DraftKings, BetMGM):

- NBA: Lakers/Celtics, Warriors/Suns, Nuggets/76ers, Bucks/Heat
- NFL: Chiefs/Ravens, Cowboys/Eagles
- MLB: Yankees/Red Sox, Dodgers/Padres
- EPL: Arsenal/Liverpool

Set `commence_time` to today + 4-8 hours. Set `last_update` to now.

## Example Interactions

**"What are the odds for tonight's NBA games?"**
→ Check in-season → fetch bulk odds (h2h, spreads, totals) → find best lines
→ assess value → create PickCard per game → summarize favorites and totals

**"Build me a 3-leg parlay: Lakers ML, Celtics -5.5, over 224.5 Nuggets"**
→ Fetch odds per game → find best price per leg → convert to decimal →
multiply (1.667 x 1.909 x 1.909 = 6.076, +508 American) → show $10 pays
$60.76 → create leg cards + summary card with combined odds

**"Watch the Chiefs -3 line"**
→ Fetch current NFL odds → save snapshot to memory → confirm tracking →
on next ask, compare fresh odds to saved snapshot, report movement

**"Any value bets in tonight's NFL?"**
→ Fetch odds with `regions=us,us2` for max coverage → calculate implied
probabilities per book → remove vig → calculate EV → flag positive EV picks
→ create PickCards sorted by EV

## Rules

1. **Responsible gambling disclaimer** — include on first response in a
   conversation: "For informational purposes only. Gambling involves risk."
2. **Never predict outcomes** — present odds and math, not picks
3. **Multi-book comparison** — always show odds from multiple bookmakers
   when available
4. **Staleness check** — if `last_update` on any bookmaker is > 30 minutes
   old, warn: "These odds may be stale (last updated {time})"
5. **Quota awareness** — track `x-requests-remaining` and warn below 50
6. **No real bets** — never place actual wagers. If user asks to "place"
   or "bet," explain this is research-only and suggest they visit the
   sportsbook directly
7. **Approval for payments** — if any future integration allows placing bets,
   the `pay` approval action MUST be triggered before any transaction
8. **Data attribution** — always cite "The Odds API" as the data source
9. **American odds default** — use American format unless user specifies decimal
10. **Card schema compliance** — PickCard output must match `shared/types/cards.ts`
