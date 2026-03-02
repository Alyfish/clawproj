---
name: betting-odds
description: >-
  Get sports betting odds, track line movement, build bet slips, and generate
  game recaps. Use whenever the user mentions odds, betting lines, spreads,
  parlays, moneyline, who's favored, over/under, point spread, totals, prop
  bets, value bet, line movement, best lines, sportsbook comparison, implied
  probability, vig, juice, or any sports wagering topic — even if they don't
  explicitly say "betting."
tools: [http_request, code_execution, create_card, save_memory]
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
- If credential is missing, operate in **mock mode** (see below)

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

## Mock Mode

When `CLAWBOT_CRED_ODDS_API` is not set, generate realistic synthetic data.
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
