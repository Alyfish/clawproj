# ClawBot — AI Agent for iPhone

## What We're Building

ClawBot is a mobile AI agent for iPhone that handles real-life tasks people hate doing manually — finding flights, apartment hunting, creating documents, and tracking betting lines. The user talks to ClawBot like texting a smart friend, and it does the legwork: searches, compares, ranks options, presents them as rich cards, and executes actions with user approval.

Think of it as: "What if you had a really capable personal assistant in your pocket who could actually DO things on your behalf, not just answer questions?"

## Our Reference User: Emma

Emma is a busy professional who:
- Books flights multiple times a year, cares about points optimization
- Is apartment hunting (or helps friends do it)
- Creates Google Docs/Forms/Sheets for work and side projects
- Follows sports and wants to track betting lines / build parlays
- Has an iPhone, uses it for everything
- Doesn't want to learn a new "system" — just wants to type what she needs

## Product Pillars (v1)
1. **Minimal friction** — User types task → sees cards → approves. No forms, no wizards.
2. **Visibility** — X/Twitter-style task feed + watchlists. Users always know what the agent is doing.
3. **Safe** — Always ask before submit/pay/send/delete. Every action logged. Stop anytime.
4. **Usability** — Sleek + simple. People don't need to understand "agents."
5. **Speed** — Fast drafts, ask only what's missing. Don't interrogate the user.
6. **Cost** — Hybrid (light on-device + cloud for heavy execution).

## v1 Use Cases

### Travel
- Multiple flight search with flexible dates
- Flight cards: price, layovers, baggage, timing, airline, refund, visa notes, points value
- Rankings: "Best Overall / Cheapest / Fastest / Best for Points"
- Follow-up: price monitoring, alternatives, reminders, itinerary

### Apartments
- Search + shortlist across sources
- House cards: rent, area, commute, lease terms, move-in, required docs, red flags
- Background monitoring: new listings, price drops
- Contact/apply always approval-gated ("assist mode" — agent drafts, user sends)

### Docs
- Create/update Google Sheets/Docs/Forms/Slides
- Turn messy context (WhatsApp, email, pasted text) into clean artifacts
- Webforms/applications in "assist mode" (agent fills, user reviews + submits)

### Betting (v1)
- Odds/lines tracking + alerts
- Pick cards: matchup, line, implied odds, movement, notes
- Bet slip builder + reminders
- No auto-placing bets — always user-confirmed

## User Journey Examples

### Travel: "Find me flights SF → London, flexible by 2 days, I have points."
Agent: asks dates/budget/preferences → searches → generates flight cards → ranks → user picks → agent offers hold/book/itinerary → monitors price after

### Apartments: "Find a 1-bed in Austin under 2.3k, close to downtown, move-in April."
Agent: asks filters/dealbreakers → searches → builds house cards → user saves picks → agent monitors new matches/price drops → drafts contact messages (approval-gated)

### Docs: "Create a Google Form for my swimming class sign-ups."
Agent: asks what info to collect → user pastes WhatsApp context → agent creates Form + Sheet + draft message → user approves → follow-up: "3 sign-ups. Want weekly summaries?"

### Betting: "Track these games and tell me the best value picks."
Agent: asks sport/league/risk level → builds pick cards + alerts → user approves bet slip additions → line movement alerts + recap

## iOS UI Patterns (Chowder-Inspired)

We're forking Chowder-iOS as our base. Key patterns we're keeping:
- Streaming chat over WebSocket (token-by-token)
- Thinking steps / tool activity shown inline (shimmer → 150ms fade on response)
- Live Activity on lock screen while tasks run
- Local chat history (survives relaunch, SwiftData)
- Cards inline in chat (flight, house, pick, doc cards)
- Task feed as second tab (X/Twitter-style timeline)
- Approvals inbox for pending actions

### Core Screens
1. Chat — streaming + thinking steps + inline cards
2. Cards — flight, house, pick, doc (expandable detail)
3. Watchlists + Alerts — active monitors
4. Task Timeline — X-style feed of all tasks
5. Approvals Inbox — pending user confirmations

## Web Mode (Account Copilot)

For sites without APIs: agent operates inside a real browser session (Playwright).
We don't "become the website." We show: what agent did (step log), what it found (summaries/cards), visibility (screenshots + "open on site" links).
CAPTCHA/2FA → agent pauses, user takes over, agent resumes.
All sensitive actions approval-gated.

## Tech Stack
- **iOS App:** Swift, SwiftUI, ActivityKit, URLSessionWebSocketTask, SwiftData
- **Gateway:** Node.js + TypeScript, ws library
- **Agent/Tools:** TypeScript (Node.js), Python for vision
- **Browser Automation:** Playwright (Node.js), ephemeral sandboxed sessions
- **LLM:** Claude API (Anthropic SDK)
- **Google APIs:** OAuth2 + Docs/Sheets/Forms/Slides
- **Odds Data:** The Odds API (or similar)

## Architecture
OS App (SwiftUI) ←WSS→ Claw Gateway (Node/TS) ← Agent (Brain) ← Tool Services
├── Travel Search
├── Apartments Search
├── Google Docs API
├── Betting Odds
├── Vision Extract
└── Browser Automation

- Gateway: single WebSocket control plane (chat streaming, task lifecycle, thinking steps, approvals)
- Agent: goal → plan → tool routing → card generation → approval → execution → follow-up
- Tools: each independently deployable, communicate through agent via typed interfaces

## Directory Structure
clawbot/
├── shared/types/           # TypeScript types & card schemas (SOURCE OF TRUTH)
├── server/
│   ├── gateway/
│   │   ├── core/           # WebSocket server, routing, streaming, sessions
│   │   └── approvals/      # Policy engine, approval inbox, audit trail
│   ├── agent/              # Planner, conversation state, tool routing, LLM calls
│   └── tools/
│       ├── travel/         # Flight search, ranking, price monitoring
│       ├── apartments/     # Apartment search, red flags, monitoring
│       ├── docs/           # Google OAuth + Docs/Sheets/Forms/Slides
│       ├── betting/        # Odds provider, alerts, slip builder
│       ├── vision/         # Screenshot → structured data via Claude Vision
│       └── browser/        # Playwright automation, session management
├── ios/ClawBot/
│   ├── Chat/               # Streaming chat UI + thinking steps
│   ├── Cards/              # Flight, House, Pick, Doc card views
│   ├── TaskFeed/           # Task timeline + watchlists + alerts
│   ├── Approvals/          # Approval inbox + push notifications
│   ├── LiveActivity/       # Lock screen widgets + Dynamic Island
│   └── Services/           # WebSocket client, SwiftData, auth
└── ios/ClawBotWidgets/     # Widget extension target (Live Activity)

## Code Conventions
- TypeScript: strict mode, ESM imports, Zod for runtime validation
- Swift: SwiftUI with @Observable (iOS 17+), async/await, SwiftData
- All cross-module communication via gateway WebSocket events
- Card schemas in shared/types/ are the SINGLE SOURCE OF TRUTH — never redefine
- Every risky action (submit/pay/send/delete/share_personal_info) MUST go through approval
- Functionality first — basic UI, no polish in v1
- Always emit thinking steps so iOS can show agent progress
- Keep tool services stateless and independently deployable

## Gateway WebSocket Protocol
- JSON text frames over WebSocket
- Message structure: { type: 'req'|'res'|'event', id?, method?, event?, payload }
- Stream events: agent/stream:assistant (text deltas), agent/stream:lifecycle (start/end), chat/state:delta (tool summaries), task/update, approval/requested
- Client requests: chat.send (with idempotency key), chat.history, approval.resolve, task.stop
- Reconnect with 3-second exponential backoff
- Poll chat.history every 500ms during active agent run

## Safety Rules (NON-NEGOTIABLE)
- Never auto-execute: submit, pay, send, delete, share personal info
- Browser automation always ephemeral sandboxed sessions
- Vision extraction always requires user confirmation of extracted fields
- Monitoring tasks must have "stop" always available
- All actions logged with audit trail (timestamp, action, decision, context)
- CAPTCHA/2FA → pause and ask user to take over