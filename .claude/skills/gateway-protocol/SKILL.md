---
name: gateway-protocol
description: Use when writing code that sends or receives WebSocket messages through the Claw Gateway. Applies to both server-side gateway code and iOS client code.
user-invocable: false
---

# Claw Gateway WebSocket Protocol

All messages are JSON text frames with this structure:
```json
{
  "type": "req" | "res" | "event",
  "id": "unique-id (for req/res pairs)",
  "method": "chat.send | chat.history | approval.resolve | task.stop",
  "event": "agent/stream:assistant | agent/stream:lifecycle | chat/state:delta | task/update | approval/requested",
  "payload": { ... }
}
```

## Stream Events (server → client)
- `agent/stream:assistant` — text delta tokens for streaming response
- `agent/stream:lifecycle` — { status: 'start' | 'end', runId }
- `chat/state:delta` — { toolName, summary } for thinking step display
- `task/update` — task status changes, new cards, monitoring alerts
- `approval/requested` — action needs user approval before proceeding

## Client Requests (client → server)
- `chat.send` — send user message (include idempotency key)
- `chat.history` — retrieve message history for session
- `approval.resolve` — approve or deny a pending action
- `task.stop` — immediately halt a running task or monitor

## Rules
- Every `chat.send` must include an idempotency key
- Reconnect with 3-second exponential backoff
- Poll `chat.history` every 500ms while lifecycle is 'start' (for thinking steps)
- Client must handle partial/chunked JSON frames
