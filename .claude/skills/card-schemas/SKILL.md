---
name: card-schemas
description: Use when creating, rendering, or processing card data (FlightCard, HouseCard, PickCard, DocCard). Reference the canonical schemas in shared/types/.
user-invocable: false
---

# Card Schemas Reference

Always import card types from `shared/types/cards.ts`. Never redefine card structures inline.

## Card Types
- **FlightCard**: airline, route, times, price, layovers, baggage, refund, visa, points, ranking
- **HouseCard**: address, rent, bedrooms, area, commute, lease, moveIn, requiredDocs, redFlags
- **PickCard**: matchup, sport, league, line, impliedOdds, movement, notes, valueRating
- **DocCard**: docType, title, previewText, googleDocsUrl, lastModified

## Rankings (FlightCard)
Use these exact labels: "Best Overall", "Cheapest", "Fastest", "Best for Points"

## Red Flags (HouseCard)
Auto-detect: unusual deposit amounts, no-pet policies hidden in fine print, short lease terms, broker fees not disclosed upfront.

When generating cards from tool service results, always validate against the Zod schema before sending to the gateway.
