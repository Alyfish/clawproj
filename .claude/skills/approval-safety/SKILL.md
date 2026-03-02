---
name: approval-safety
description: Use when implementing any action that could affect the user's accounts, money, data, or external services. Ensures all risky actions go through the approval flow.
user-invocable: false
---

# Approval Safety Rules

## Always-Ask Actions (MUST trigger approval)
- `submit` — form submissions, applications, bookings
- `pay` — any payment or financial transaction
- `send` — messages, emails, communications on behalf of user
- `delete` — removing data, canceling bookings
- `share_personal_info` — sharing name, email, phone, address with third parties

## Implementation Pattern
```typescript
// Before executing a risky action:
await gateway.emit('approval/requested', {
  id: generateId(),
  taskId: currentTask.id,
  action: 'submit',
  description: 'Submit rental application to 123 Main St',
  details: { /* relevant context */ }
});
// STOP execution here. Wait for approval/resolved event.
// Never proceed without explicit approval.
```

## Audit Trail
Every action (approved or denied) must be logged with: timestamp, action type, user decision, full context.
