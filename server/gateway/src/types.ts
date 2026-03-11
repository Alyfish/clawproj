import type { WebSocket } from 'ws';

// ── Re-export all shared types ────────────────────────────────────

export type {
  ApprovalAction,
  ApprovalDecision,
  ApprovalRequest,
  ApprovalResponse,
  ApprovalPolicy,
  AuditEntry,
} from '../../../shared/types/approvals.js';

export type {
  FlightRoute,
  Price,
  PointsValue,
  FlightRanking,
  FlightCard,
  Rent,
  Commute,
  HouseCard,
  Matchup,
  PickCard,
  DocCard,
  AnyCard,
} from '../../../shared/types/cards.js';

export type {
  WatchlistItem,
  MonitoringAlert,
} from '../../../shared/types/monitoring.js';

export type {
  TaskStatus,
  ThinkingStep,
  Task,
  TaskUpdate,
} from '../../../shared/types/tasks.js';

export type {
  WSMessage,
  StreamAssistantEvent,
  StreamLifecycleEvent,
  ChatStateDeltaEvent,
  TaskUpdateEvent,
  ApprovalRequestedEvent,
  WatchlistAlertPayload,
  WatchlistAlertEvent,
  StreamEvent,
  ChatSendPayload,
  ApprovalResolvePayload,
  TaskStopPayload,
  CardActionPayload,
} from '../../../shared/types/gateway.js';

// ── Gateway-local types ───────────────────────────────────────────

export type ClientRole = 'operator' | 'node';

export interface ConnectPayload {
  role: ClientRole;
  scopes: string[];
  authToken?: string;
  /** Join an existing session; if omitted, a new session is created */
  sessionId?: string;
  /** Provide a previous deviceToken to attempt reconnection */
  deviceToken?: string;
}

export interface ConnectResponse {
  deviceToken: string;
  sessionId: string;
}

export interface ConnectedClient {
  ws: WebSocket;
  deviceToken: string;
  role: ClientRole;
  scopes: string[];
  sessionId: string;
  /** ISO 8601 */
  connectedAt: string;
  /** ISO 8601 — updated on each message */
  lastSeen: string;
}

export interface DisconnectedClient {
  deviceToken: string;
  role: ClientRole;
  scopes: string[];
  sessionId: string;
  /** ISO 8601 */
  disconnectedAt: string;
}

export interface MessageHistoryEntry {
  id: string;
  sessionId: string;
  sender: 'operator' | 'agent' | 'system';
  message: import('../../../shared/types/gateway.js').WSMessage;
  /** ISO 8601 */
  timestamp: string;
}

export interface Session {
  id: string;
  /** All currently connected clients, keyed by deviceToken */
  clients: Map<string, ConnectedClient>;
  /** Ordered message history */
  history: MessageHistoryEntry[];
  /** Idempotency keys already processed */
  processedKeys: Set<string>;
  /** ISO 8601 */
  createdAt: string;
  /** ISO 8601 */
  lastActivity: string;
}

/** Hook called when an approval-requiring action is requested. Passthrough for now. */
export type ApprovalHookFn = (
  action: string,
  context: Record<string, unknown>,
) => Promise<void>;

/** Hook called when a pushable event occurs (task complete, price alert, etc.) */
export type PushHookFn = (
  sessionId: string,
  event: string,
  payload: Record<string, unknown>,
) => void;

export interface LogEntry {
  level: 'info' | 'warn' | 'error';
  event: string;
  data?: Record<string, unknown>;
  /** ISO 8601 */
  timestamp: string;
}
