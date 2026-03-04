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
  payload: { card: BaseCard };
}

export interface MemoryUpdatedEvent {
  event: 'agent/memory:updated';
  payload: { key: string; operation: 'set' | 'delete' };
}

// ── Browser login flow events (ephemeral — not persisted) ──

export interface BrowserLoginFrameEvent {
  event: 'browser/login:frame';
  payload: {
    imageBase64: string;
    url: string;
    profile: string;
    pageTitle: string;
    timestamp: string;
    elements: Array<{
      ref: number;
      tag: string;
      type: string | null;
      text: string;
      rect: { x: number; y: number; w: number; h: number };
    }>;
  };
}

export interface LoginFlowEndEvent {
  event: 'browser/login:end';
  payload: {
    profile: string;
    authenticated: boolean;
    domain: string;
  };
}

// ── Scheduler events (cron/watch system) ────────────────────

export interface ScheduleTaskTriggerEvent {
  event: 'schedule/task:trigger';
  payload: {
    jobId: string;
    taskDescription: string;
    skillName: string;
    checkInstructions: string;
    payload: Record<string, unknown>;
    previousResult?: {
      data: Record<string, unknown>;
      executedAt: string;
    };
  };
}

export interface ScheduleTaskResultEvent {
  event: 'schedule/task:result';
  payload: {
    jobId: string;
    status: 'ok' | 'error';
    data: Record<string, unknown>;
    summary: string;
  };
}

export interface ScheduleWatchUpdateEvent {
  event: 'schedule/watch:update';
  payload: {
    action: 'created' | 'updated' | 'removed' | 'paused' | 'resumed' | 'alert';
    watch?: {
      id: string;
      type: string;
      description: string;
      interval: string;
      lastChecked: string | null;
      active: boolean;
      nextRun: string | null;
    };
    alert?: {
      id: string;
      watchId: string;
      message: string;
      data: Record<string, unknown>;
      timestamp: string;
    };
  };
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
  | MemoryUpdatedEvent
  | BrowserLoginFrameEvent
  | LoginFlowEndEvent
  | ScheduleTaskTriggerEvent
  | ScheduleTaskResultEvent
  | ScheduleWatchUpdateEvent;

// ── Client request payloads (client → server) ──────────────

export interface ChatSendPayload {
  text: string;
  /** Idempotency key — optional */
  idempotencyKey?: string;
}

export interface ApprovalResolvePayload {
  approvalId: string;
  decision: ApprovalResponse['decision'];
}

export interface TaskStopPayload {
  taskId: string;
}

export interface LoginInputPayload {
  profile: string;
  ref: number;
  text: string;
}

export interface LoginClickPayload {
  profile: string;
  ref: number;
}

export interface LoginDonePayload {
  profile: string;
}
