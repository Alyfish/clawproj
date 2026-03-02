import type { TaskUpdate, ThinkingStep } from './tasks.js';
import type { ApprovalRequest, ApprovalResponse } from './approvals.js';
import type { BaseCard } from './cards.js';

// ── Base message envelope ───────────────────────────────────

export interface WSMessage {
  type: 'req' | 'res' | 'event';
  /** Correlation ID for req/res pairs */
  id?: string;
  /** Method name for requests: chat.send, chat.history, approval.resolve, task.stop */
  method?: string;
  /** Event name for server-pushed events */
  event?: string;
  payload?: unknown;
}

// ── Stream events (server → client) ────────────────────────

export interface StreamAssistantEvent {
  event: 'agent/stream:assistant';
  /** Token-by-token text delta */
  payload: { delta: string };
}

export interface StreamLifecycleEvent {
  event: 'agent/stream:lifecycle';
  payload: { status: 'start' | 'end'; runId: string };
}

export interface ChatStateDeltaEvent {
  event: 'chat/state:delta';
  payload: { thinkingStep: ThinkingStep; sessionId?: string };
}

export interface TaskUpdateEvent {
  event: 'task/update';
  payload: TaskUpdate;
}

export interface ApprovalRequestedEvent {
  event: 'approval/requested';
  payload: ApprovalRequest;
}

export interface ToolStartEvent {
  event: 'agent/tool:start';
  payload: { callId: string; toolName: string; description: string };
}

export interface ToolEndEvent {
  event: 'agent/tool:end';
  payload: {
    callId: string;
    toolName: string;
    success: boolean;
    summary: string;
    durationMs?: number;
  };
}

export interface SkillLoadedEvent {
  event: 'agent/skill:loaded';
  payload: { skillName: string; description?: string };
}

export interface CardCreatedEvent {
  event: 'card/created';
  payload: BaseCard;
}

export interface MemoryUpdatedEvent {
  event: 'agent/memory:updated';
  payload: { key: string; operation: 'set' | 'delete' };
}

export type StreamEvent =
  | StreamAssistantEvent
  | StreamLifecycleEvent
  | ChatStateDeltaEvent
  | TaskUpdateEvent
  | ApprovalRequestedEvent
  | ToolStartEvent
  | ToolEndEvent
  | SkillLoadedEvent
  | CardCreatedEvent
  | MemoryUpdatedEvent;

// ── Client request payloads (client → server) ──────────────

export interface ChatSendPayload {
  message: string;
  /** Idempotency key — required */
  idempotencyKey: string;
}

export interface ApprovalResolvePayload {
  approvalId: string;
  decision: ApprovalResponse['decision'];
}

export interface TaskStopPayload {
  taskId: string;
}
