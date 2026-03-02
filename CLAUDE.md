# ClawBot

ClawBot is a mobile AI agent for iPhone that handles real-life tasks (flights, apartments, docs, betting) via a conversational interface with rich cards and approval-gated actions.

## Canonical Specification
See `clawbot-complete-breakdown.md` for the full product spec, architecture, and use cases. Use mcps, skills and agents to help you do tasks.

## Tech Stack
- **iOS App:** Swift, SwiftUI (iOS 17+), SwiftData, URLSessionWebSocketTask
- **Gateway:** Node.js, TypeScript (strict, ESM), ws library
- **Validation:** Zod schemas for all runtime data
- **LLM:** Claude API (Anthropic SDK)
- **Testing:** Vitest (server), XCTest (iOS)

## Source of Truth
- Card schemas: `shared/types/cards.ts`
- Gateway protocol: `.claude/skills/gateway-protocol/SKILL.md`
- Safety rules: `.claude/skills/approval-safety/SKILL.md`

## Code Conventions
- TypeScript: strict mode, ESM imports, Zod validation
- Swift: @Observable (not ObservableObject), async/await, SwiftData
- All cross-module communication via gateway WebSocket events
- Never redefine types that exist in shared/types/
- Every risky action (submit/pay/send/delete/share_personal_info) must go through approval

## Subagents
- `ios-swift` — iOS app development (sonnet)
- `backend-ts` — Server/gateway/tools development (sonnet)
- `architect` — Interface design and cross-module coordination (opus, read-only)
