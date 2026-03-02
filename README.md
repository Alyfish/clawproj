# ClawBot

An AI agent for iPhone that executes real-life tasks — booking flights, finding apartments, managing documents, tracking odds — through a conversational interface with rich cards and approval-gated actions.

Think Rabbit R1 or Humane AI Pin, but as a native iPhone app powered by Claude.

## How It Works

```
iOS App (SwiftUI)
    |
    | WebSocket (streaming)
    v
Gateway Server (Node.js / TypeScript)
    |-- Session Manager (routing, reconnect)
    |-- Approval Engine (safety rules, audit trail)
    v
Agent Service (Python)
    |-- Claude API (streaming, tool use)
    |-- 12+ Tools (HTTP, browser, vision, code, memory)
    |-- BM25 Memory Search (persistent context)
    |-- Credential Store (OAuth2, API keys)
    v
External APIs (flights, apartments, docs, odds)
```

You talk to ClawBot like a person. It figures out what tools to use, executes them, and presents results as interactive cards you can compare side-by-side. Every risky action (paying, sending, deleting, submitting, sharing personal info) requires your explicit approval before it happens.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **iOS** | Swift, SwiftUI (iOS 17+), SwiftData, URLSessionWebSocketTask |
| **Gateway** | Node.js, TypeScript (strict, ESM), ws, Zod validation |
| **Agent** | Python 3.9+, Anthropic SDK, httpx, BM25 search |
| **LLM** | Claude API with streaming + tool use |
| **Testing** | pytest (225 tests), node:test (12 tests), XCTest |

## What It Does

- **Rich Cards** — Flight, apartment, document, and pick cards with structured data, not walls of text
- **Side-by-Side Comparison** — Compare options with ranking badges (Best Overall, Cheapest, etc.)
- **Live Task Feed** — See everything the agent is doing in real-time with thinking steps
- **Approval Gates** — 5 hardcoded safety-critical actions that always require user approval
- **Persistent Memory** — Agent remembers preferences, past searches, and context across conversations
- **Watchlists** — Monitor prices, listings, or odds with smart alerts
- **Credential Management** — Secure storage for API keys, OAuth2 tokens, and HTTP auth with auto-refresh

## Project Structure

```
clawproj/
|-- shared/types/           # Source-of-truth TypeScript schemas
|   |-- cards.ts            #   Flight, House, Pick, Doc card types
|   |-- gateway.ts          #   WebSocket protocol (WSMessage, StreamEvent)
|   |-- approvals.ts        #   Safety rules, audit trail types
|   |-- tasks.ts            #   Task lifecycle, pending approvals
|   +-- monitoring.ts       #   Watchlists, alerts
|
|-- server/
|   |-- gateway/            # WebSocket control plane
|   |   |-- src/            #   ws-server, message-router, session-manager
|   |   +-- approvals/      #   policy-engine, approval-manager, audit-log
|   |
|   +-- agent/              # Python agentic loop
|       |-- agent.py        #   Core loop: Claude API -> tool dispatch -> stream
|       |-- context_builder.py  # System prompt assembly + memory injection
|       |-- credential_store.py # Secure credential management (5 auth types)
|       |-- memory/         #   BM25 search engine + persistent markdown store
|       |-- tools/          #   12+ tools (HTTP, browser, vision, code, cards)
|       +-- tests/          #   225 automated tests
|
+-- ios/ClawBot/            # Native iPhone app
    +-- ClawBot/
        |-- App/            #   ClawBotApp, ContentView (4-tab hub)
        |-- Chat/           #   Streaming chat, thinking steps, markdown
        |-- Cards/          #   Flight, House, Doc, Pick card views
        |-- TaskFeed/       #   Task timeline, watchlists, alerts
        |-- Approvals/      #   Approval inbox, detail review
        |-- Models/         #   ChatMessage, Cards, Tasks, Approvals
        +-- Input/          #   Deep linking, photo input
```

## Getting Started

**Gateway:**
```bash
cd server/gateway
npm install
npm run dev                    # Starts WebSocket server on :8080
```

**Agent:**
```bash
pip install -r server/agent/requirements.txt
export ANTHROPIC_API_KEY=sk-...
python -m server.agent.main --test     # Test mode (stdin/stdout)
python -m server.agent.main            # Connect to gateway
```

**iOS:**
Open `ios/ClawBot/ClawBot/ClawBot.xcodeproj` in Xcode and build.

**Tests:**
```bash
python3 -m pytest server/agent/tests/ -v      # 225 tests
cd server/gateway && npx tsx approvals/__tests__/policy-engine.test.ts  # 12 tests
```

## Safety & Approvals

Five actions are **hardcoded to always require approval** — no configuration can override this:

| Action | Example |
|--------|---------|
| `pay` | Booking a flight, paying for a service |
| `send` | Sending an email or message |
| `delete` | Removing a document or data |
| `submit` | Submitting a form or application |
| `share_personal_info` | Sharing name, email, phone, address |

The approval system includes a policy engine, async approval lifecycle with timeouts, and a complete audit trail of every action check.

## Architecture Highlights

- **Agentic Loop**: Agent calls Claude with context -> Claude returns tool_use -> agent executes tool -> loop until done. Max 25 iterations per turn.
- **WebSocket Gateway**: Single control plane for all connections. Handles session management, message routing, and approval lifecycle.
- **BM25 Memory Search**: File-backed persistent memory with keyword scoring, tag filtering, and recency boosting. No external database required.
- **Credential Store**: Supports API keys, OAuth2 (with auto-refresh), Bearer tokens, Basic auth, and custom headers. File permissions 0o600, never logs secrets.
- **Shared Type System**: Card schemas and gateway protocol defined once in TypeScript, matched 1:1 by Swift Codable models on iOS.

## Similar To

- **Rabbit R1** / **Humane AI Pin** — AI agents for real-world tasks, but ClawBot runs on your existing iPhone
- **ChatGPT with plugins** — Tool use + conversation, but ClawBot adds rich cards, approval gates, and a native mobile experience
- **Apple Intelligence** — On-device AI, but ClawBot is task-execution focused with external API integration

## Current Status

**Foundation complete. Ready for live API integration.**

- iOS app: 50+ Swift files, all screens built, zero compilation errors
- Gateway: WebSocket server with session management + approval engine
- Agent: Streaming agentic loop with 12+ tools, memory, and credentials
- Tests: 237 automated tests passing
- Next steps: Wire live flight/apartment/docs APIs, deploy, real-device testing
