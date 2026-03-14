import { v4 as uuidv4 } from 'uuid';
import { z } from 'zod';
import type { WebSocket } from 'ws';
import type {
  ConnectedClient,
  ConnectPayload,
  WSMessage,
  MessageHistoryEntry,
  ApprovalHookFn,
  PushHookFn,
} from './types.js';
import SessionManager from './session-manager.js';
import type { GatewayDB } from './persistence.js';
import type { Scheduler } from './scheduler.js';

// ── Zod schemas ──────────────────────────────────────────────

const ChatSendSchema = z.object({
  text: z.string().min(1),
  idempotencyKey: z.string().optional(),
});

const ApprovalResolveSchema = z.object({
  approvalId: z.string(),
  decision: z.enum(['approved', 'denied']),
});

const TaskStopSchema = z.object({
  taskId: z.string(),
});

const LoginInputSchema = z.object({
  profile: z.string().min(1),
  ref: z.number().int().min(0),
  text: z.string(),
});

const LoginClickSchema = z.object({
  profile: z.string().min(1),
  ref: z.number().int().min(0),
});

const LoginDoneSchema = z.object({
  profile: z.string().min(1),
});

const CardActionSchema = z.object({
  action: z.string().min(1),
  cardType: z.string().min(1),
  cardData: z.record(z.unknown()).default({}),
});

const DeviceRegisterPushSchema = z.object({
  platform: z.enum(['ios']),
  deviceToken: z.string().min(10).max(200),
});

const ScheduleCreateSchema = z.object({
  cronExpression: z.string().optional(),
  interval: z.string().optional(),
  skillName: z.string().default('price-monitor'),
  taskDescription: z.string().min(1),
  checkInstructions: z.string().min(1),
  payload: z.record(z.unknown()).optional(),
});

const ScheduleIdSchema = z.object({
  watchId: z.string().min(1),
});

const WatchlistMarkReadSchema = z.object({
  alertIds: z.array(z.string()).optional(),
  all: z.boolean().optional(),
});

const CredentialResponseSchema = z.object({
  requestId: z.string().uuid(),
  domain: z.string().min(1),
  credentials: z
    .array(
      z.object({
        username: z.string(),
        password: z.string(),
      }),
    )
    .min(1),
});

const CredentialNoneSchema = z.object({
  requestId: z.string().uuid(),
  domain: z.string().min(1),
  reason: z.enum(['no_credentials', 'user_denied', 'not_imported']),
});

const OAuthTokenRefreshedSchema = z.object({
  service: z.string().min(1),
  token: z.string().min(1),
  requestId: z.string().uuid().optional(),
});

const WSMessageSchema = z.object({
  type: z.enum(['req', 'res', 'event']),
  id: z.string().optional(),
  method: z.string().optional(),
  event: z.string().optional(),
  payload: z.any().optional(),
});

// ── Sensitive methods (never logged or persisted) ────────────

const SENSITIVE_EVENTS = new Set([
  'credential/request',
  'credential/response',
  'credential/none',
  'credential/token',
  'credential/token:expired',
  'credential/token:refresh',
]);

const CREDENTIAL_TIMEOUT_MS = 30_000;

// ── Error codes ──────────────────────────────────────────────

const ErrorCodes = {
  PARSE_ERROR: 'PARSE_ERROR',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  UNKNOWN_METHOD: 'UNKNOWN_METHOD',
  NO_AGENT: 'NO_AGENT',
  SESSION_NOT_FOUND: 'SESSION_NOT_FOUND',
  AUTH_FAILED: 'AUTH_FAILED',
} as const;

// ── Logging ──────────────────────────────────────────────────

function log(
  level: 'info' | 'warn' | 'error',
  event: string,
  data?: Record<string, unknown>,
): void {
  console.log(
    JSON.stringify({ level, event, data, timestamp: new Date().toISOString() }),
  );
}

// ── Router ───────────────────────────────────────────────────

export default class MessageRouter {
  private sessions: SessionManager;
  private approvalHook: ApprovalHookFn;
  private pushHook: PushHookFn;
  private db: GatewayDB | null;
  private scheduler: Scheduler | null = null;
  private pendingCredentialRequests = new Map<
    string,
    { sessionId: string; timeoutId: NodeJS.Timeout }
  >();

  /** OAuth tokens keyed by sessionId — never persisted */
  private oauthTokens = new Map<
    string,
    { token: string; service: string; providedBy: string; receivedAt: string }
  >();

  /** Pending token refresh requests keyed by requestId — 30s timeout */
  private pendingTokenRefreshRequests = new Map<
    string,
    { sessionId: string; timeoutId: NodeJS.Timeout }
  >();

  constructor(
    sessions: SessionManager,
    approvalHook?: ApprovalHookFn,
    pushHook?: PushHookFn,
    db?: GatewayDB,
  ) {
    this.sessions = sessions;
    this.approvalHook = approvalHook ?? (async () => {});
    this.pushHook = pushHook ?? (() => {});
    this.db = db ?? null;
  }

  setScheduler(scheduler: Scheduler): void {
    this.scheduler = scheduler;
  }

  handleMessage(client: ConnectedClient, raw: string): void {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      this.sendError(
        client.ws,
        undefined,
        ErrorCodes.PARSE_ERROR,
        'Invalid JSON',
      );
      return;
    }

    const result = WSMessageSchema.safeParse(parsed);
    if (!result.success) {
      this.sendError(
        client.ws,
        undefined,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid message format: ${result.error.message}`,
      );
      return;
    }

    const msg = parsed as WSMessage;

    if (msg.type === 'req') {
      this.handleRequest(client, msg);
    } else if (msg.type === 'event') {
      this.handleEvent(client, msg);
    } else {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.UNKNOWN_METHOD,
        `Unsupported message type: ${msg.type}`,
      );
    }
  }

  // ── Request routing ──────────────────────────────────────

  private handleRequest(client: ConnectedClient, msg: WSMessage): void {
    switch (msg.method) {
      case 'chat.send':
        this.handleChatSend(client, msg);
        break;
      case 'chat.history':
        this.handleChatHistory(client, msg);
        break;
      case 'approval.resolve':
        this.handleApprovalResolve(client, msg);
        break;
      case 'task.stop':
        this.handleTaskStop(client, msg);
        break;
      case 'login.input':
        this.handleLoginInput(client, msg);
        break;
      case 'login.click':
        this.handleLoginClick(client, msg);
        break;
      case 'login.done':
        this.handleLoginDone(client, msg);
        break;
      case 'device.registerPush':
        this.handleDeviceRegisterPush(client, msg);
        break;
      case 'schedule.create':
        this.handleScheduleCreate(client, msg);
        break;
      case 'schedule.list':
        this.handleScheduleList(client, msg);
        break;
      case 'schedule.remove':
        this.handleScheduleRemove(client, msg);
        break;
      case 'schedule.pause':
        this.handleSchedulePause(client, msg);
        break;
      case 'schedule.resume':
        this.handleScheduleResume(client, msg);
        break;
      case 'card.action':
        this.handleCardAction(client, msg);
        break;
      case 'watchlist.alerts.fetch':
        this.handleWatchlistAlertsFetch(client, msg);
        break;
      case 'watchlist.alerts.markRead':
        this.handleWatchlistAlertsMarkRead(client, msg);
        break;
      case 'credential.response':
        this.handleCredentialResponse(client, msg);
        break;
      case 'credential.none':
        this.handleCredentialNone(client, msg);
        break;
      case 'credential.tokenRefreshed':
        this.handleTokenRefreshed(client, msg);
        break;
      default:
        this.sendError(
          client.ws,
          msg.id,
          ErrorCodes.UNKNOWN_METHOD,
          `Unknown method: ${msg.method}`,
        );
    }
  }

  // ── chat.send ────────────────────────────────────────────

  private handleChatSend(client: ConnectedClient, msg: WSMessage): void {
    const result = ChatSendSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid chat.send payload: ${result.error.message}`,
      );
      return;
    }

    const { text, idempotencyKey } = result.data;

    // Idempotency check
    if (idempotencyKey) {
      if (this.sessions.hasProcessedKey(client.sessionId, idempotencyKey)) {
        this.sendTo(client.ws, {
          type: 'res',
          id: msg.id,
          method: 'chat.send',
          payload: { status: 'duplicate' },
        });
        return;
      }
      this.sessions.markKeyProcessed(client.sessionId, idempotencyKey);
    }

    // Store in history
    const historyEntry: MessageHistoryEntry = {
      id: uuidv4(),
      sessionId: client.sessionId,
      sender: 'operator',
      message: msg,
      timestamp: new Date().toISOString(),
    };
    this.sessions.addHistory(client.sessionId, historyEntry);

    // Find agent node
    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'chat/message:new',
      payload: {
        text,
        sessionId: client.sessionId,
        from: client.deviceToken,
        timestamp: new Date().toISOString(),
      },
    });

    // Respond to operator
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'chat.send',
      payload: { status: 'sent' },
    });
  }

  // ── chat.history ─────────────────────────────────────────

  private handleChatHistory(client: ConnectedClient, msg: WSMessage): void {
    const history = this.sessions.getHistory(client.sessionId);
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'chat.history',
      payload: { messages: history },
    });
  }

  // ── approval.resolve ─────────────────────────────────────

  private handleApprovalResolve(client: ConnectedClient, msg: WSMessage): void {
    const result = ApprovalResolveSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid approval.resolve payload: ${result.error.message}`,
      );
      return;
    }

    const { approvalId, decision } = result.data;

    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'approval/resolved',
      payload: {
        approvalId,
        decision,
        decidedAt: new Date().toISOString(),
      },
    });

    // Respond to operator
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'approval.resolve',
      payload: { status: 'resolved' },
    });
  }

  // ── task.stop ────────────────────────────────────────────

  private handleTaskStop(client: ConnectedClient, msg: WSMessage): void {
    const result = TaskStopSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid task.stop payload: ${result.error.message}`,
      );
      return;
    }

    const { taskId } = result.data;

    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'task/stop',
      payload: { taskId },
    });

    // Respond to operator
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'task.stop',
      payload: { status: 'stopped' },
    });
  }

  // ── login.input ──────────────────────────────────────────

  private handleLoginInput(client: ConnectedClient, msg: WSMessage): void {
    const result = LoginInputSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid login.input payload: ${result.error.message}`,
      );
      return;
    }

    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'login/input',
      payload: { ...result.data, sessionId: client.sessionId },
    });

    // Respond to operator
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'login.input',
      payload: { status: 'sent' },
    });
  }

  // ── login.click ──────────────────────────────────────────

  private handleLoginClick(client: ConnectedClient, msg: WSMessage): void {
    const result = LoginClickSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid login.click payload: ${result.error.message}`,
      );
      return;
    }

    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'login/click',
      payload: { ...result.data, sessionId: client.sessionId },
    });

    // Respond to operator
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'login.click',
      payload: { status: 'sent' },
    });
  }

  // ── login.done ───────────────────────────────────────────

  private handleLoginDone(client: ConnectedClient, msg: WSMessage): void {
    const result = LoginDoneSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid login.done payload: ${result.error.message}`,
      );
      return;
    }

    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'login/done',
      payload: { ...result.data, sessionId: client.sessionId },
    });

    // Respond to operator
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'login.done',
      payload: { status: 'sent' },
    });
  }

  // ── card.action ──────────────────────────────────────────

  private handleCardAction(client: ConnectedClient, msg: WSMessage): void {
    const result = CardActionSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid card.action payload: ${result.error.message}`,
      );
      return;
    }

    const { action, cardType, cardData } = result.data;

    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    log('info', 'card:action_received', {
      action,
      cardType,
      sessionId: client.sessionId,
    });

    // Forward to agent as event
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'card/action',
      payload: {
        action,
        cardType,
        cardData,
        sessionId: client.sessionId,
        from: client.deviceToken,
        timestamp: new Date().toISOString(),
      },
    });

    // Store in history
    const historyEntry: MessageHistoryEntry = {
      id: uuidv4(),
      sessionId: client.sessionId,
      sender: 'operator',
      message: msg,
      timestamp: new Date().toISOString(),
    };
    this.sessions.addHistory(client.sessionId, historyEntry);

    // Respond to operator
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'card.action',
      payload: { status: 'received', action },
    });
  }

  // ── Event handling (from node clients) ───────────────────

  private handleEvent(client: ConnectedClient, msg: WSMessage): void {
    if (client.role !== 'node') {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.AUTH_FAILED,
        'Only node clients can send events',
      );
      return;
    }

    // Fire approval hook if this is an approval request
    if (msg.event === 'approval/requested') {
      const payload = msg.payload as Record<string, unknown> | undefined;
      this.approvalHook(
        (payload?.action as string) ?? 'unknown',
        payload ?? {},
      ).catch((err: unknown) => {
        const message =
          err instanceof Error ? err.message : 'Approval hook error';
        log('error', 'approval_hook:error', { error: message });
      });
    }

    // Handle credential requests — route to operators with 30s timeout
    if (msg.event === 'credential/request') {
      const payload = msg.payload as
        | { requestId?: string; domain?: string; reason?: string }
        | undefined;
      const requestId = payload?.requestId;
      if (requestId) {
        const timeoutId = setTimeout(() => {
          this.pendingCredentialRequests.delete(requestId);
          const agentNode = this.findAgentNode(client.sessionId);
          if (agentNode) {
            this.sendTo(agentNode.ws, {
              type: 'event',
              event: 'credential/none',
              payload: {
                requestId,
                domain: payload?.domain ?? '',
                reason: 'timeout',
              },
            });
          }
        }, CREDENTIAL_TIMEOUT_MS);
        this.pendingCredentialRequests.set(requestId, {
          sessionId: client.sessionId,
          timeoutId,
        });
      }
      this.broadcastToOperators(client.sessionId, msg);
      return; // SENSITIVE — skip history
    }

    // Handle OAuth token expiry signals — route refresh to operators with 30s timeout
    if (msg.event === 'credential/token:expired') {
      const payload = msg.payload as { service?: string } | undefined;
      const service = payload?.service ?? 'google';
      const requestId = uuidv4();

      const timeoutId = setTimeout(() => {
        this.pendingTokenRefreshRequests.delete(requestId);
        const agentNode = this.findAgentNode(client.sessionId);
        if (agentNode) {
          this.sendTo(agentNode.ws, {
            type: 'event',
            event: 'credential/none',
            payload: {
              requestId,
              domain: `oauth:${service}`,
              reason: 'timeout',
            },
          });
        }
      }, CREDENTIAL_TIMEOUT_MS);

      this.pendingTokenRefreshRequests.set(requestId, {
        sessionId: client.sessionId,
        timeoutId,
      });

      // Broadcast refresh request to all operators in the session
      this.broadcastToOperators(client.sessionId, {
        type: 'event',
        event: 'credential/token:refresh',
        payload: {
          service,
          requestId,
          sessionId: client.sessionId,
        },
      });

      return; // SENSITIVE — skip history
    }

    // Handle schedule task results from agent
    if (msg.event === 'schedule/task:result' && this.scheduler) {
      const payload = msg.payload as Record<string, unknown> | undefined;
      if (payload?.jobId) {
        this.scheduler.handleTaskResult(payload.jobId as string, {
          status: (payload.status as 'ok' | 'error') ?? 'ok',
          data: (payload.data as Record<string, unknown>) ?? {},
          summary: (payload.summary as string) ?? '',
        });
      }
    }

    // Broadcast to all operators in the session
    this.broadcastToOperators(client.sessionId, msg);

    // Trigger push notifications for pushable events
    if (msg.event) {
      const pushableEvents = new Set([
        'approval/requested',
        'task/update',
        'monitoring/alert',
        'watchlist/alert',
      ]);
      if (pushableEvents.has(msg.event)) {
        try {
          this.pushHook(
            client.sessionId,
            msg.event,
            (msg.payload ?? {}) as Record<string, unknown>,
          );
        } catch (err: unknown) {
          const message =
            err instanceof Error ? err.message : 'Push hook error';
          log('error', 'push_hook:error', { error: message });
        }
      }
    }

    // Persist watchlist alerts to SQLite for reconnect fetch
    if (msg.event === 'watchlist/alert' && this.db) {
      const alert = msg.payload as Record<string, unknown>;
      this.db.insertWatchlistAlert(
        uuidv4(),
        (alert.watchId as string) ?? '',
        (alert.alertType as string) ?? 'custom',
        (alert.title as string) ?? '',
        (alert.message as string) ?? '',
        JSON.stringify(alert),
        client.sessionId,
      );
    }

    // Skip history for ephemeral browser login frames (~80KB each)
    // and sensitive credential events (never persisted)
    if (
      (msg.event ?? '').startsWith('browser/login:') ||
      SENSITIVE_EVENTS.has(msg.event ?? '')
    ) {
      return;
    }

    // Store in history
    const historyEntry: MessageHistoryEntry = {
      id: uuidv4(),
      sessionId: client.sessionId,
      sender: 'agent',
      message: msg,
      timestamp: new Date().toISOString(),
    };
    this.sessions.addHistory(client.sessionId, historyEntry);
  }

  // ── device.registerPush ─────────────────────────────────

  private handleDeviceRegisterPush(
    client: ConnectedClient,
    msg: WSMessage,
  ): void {
    const result = DeviceRegisterPushSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid device.registerPush payload: ${result.error.message}`,
      );
      return;
    }

    const { platform, deviceToken } = result.data;

    if (this.db) {
      this.db.registerDeviceToken(deviceToken, client.sessionId, platform);
    }

    log('info', 'device:push_registered', {
      platform,
      sessionId: client.sessionId,
      tokenPrefix: deviceToken.slice(0, 8) + '...',
    });

    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'device.registerPush',
      payload: { status: 'registered' },
    });
  }

  // ── schedule.create ─────────────────────────────────────

  private handleScheduleCreate(client: ConnectedClient, msg: WSMessage): void {
    if (!this.scheduler) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'Scheduler not available',
      );
      return;
    }
    const result = ScheduleCreateSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid schedule.create payload: ${result.error.message}`,
      );
      return;
    }
    const userId = client.sessionId;
    try {
      const job = this.scheduler.createJob({
        userId,
        cronExpression:
          result.data.cronExpression ?? result.data.interval ?? 'every_6_hours',
        skillName: result.data.skillName,
        taskDescription: result.data.taskDescription,
        checkInstructions: result.data.checkInstructions,
        payload: result.data.payload,
      });
      this.sendTo(client.ws, {
        type: 'res',
        id: msg.id,
        method: 'schedule.create',
        payload: { status: 'created', jobId: job.id, nextRun: job.next_run },
      });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to create job';
      this.sendError(client.ws, msg.id, ErrorCodes.VALIDATION_ERROR, message);
    }
  }

  // ── schedule.list ──────────────────────────────────────

  private handleScheduleList(client: ConnectedClient, msg: WSMessage): void {
    if (!this.scheduler) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'Scheduler not available',
      );
      return;
    }
    const userId = client.sessionId;
    const jobs = this.scheduler.listJobs(userId);
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'schedule.list',
      payload: { jobs },
    });
  }

  // ── schedule.remove ────────────────────────────────────

  private handleScheduleRemove(client: ConnectedClient, msg: WSMessage): void {
    if (!this.scheduler) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'Scheduler not available',
      );
      return;
    }
    const result = ScheduleIdSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid schedule.remove payload: ${result.error.message}`,
      );
      return;
    }
    const removed = this.scheduler.removeJob(result.data.watchId);
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'schedule.remove',
      payload: { status: removed ? 'removed' : 'not_found' },
    });
  }

  // ── schedule.pause ─────────────────────────────────────

  private handleSchedulePause(client: ConnectedClient, msg: WSMessage): void {
    if (!this.scheduler) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'Scheduler not available',
      );
      return;
    }
    const result = ScheduleIdSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid schedule.pause payload: ${result.error.message}`,
      );
      return;
    }
    const paused = this.scheduler.pauseJob(result.data.watchId);
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'schedule.pause',
      payload: { status: paused ? 'paused' : 'not_found' },
    });
  }

  // ── schedule.resume ────────────────────────────────────

  private handleScheduleResume(client: ConnectedClient, msg: WSMessage): void {
    if (!this.scheduler) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'Scheduler not available',
      );
      return;
    }
    const result = ScheduleIdSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid schedule.resume payload: ${result.error.message}`,
      );
      return;
    }
    const resumed = this.scheduler.resumeJob(result.data.watchId);
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'schedule.resume',
      payload: { status: resumed ? 'resumed' : 'not_found' },
    });
  }

  // ── watchlist.alerts.fetch ──────────────────────────────

  private handleWatchlistAlertsFetch(
    client: ConnectedClient,
    msg: WSMessage,
  ): void {
    if (!this.db) {
      this.sendTo(client.ws, {
        type: 'res',
        id: msg.id,
        method: 'watchlist.alerts.fetch',
        payload: { alerts: [] },
      });
      return;
    }

    const alerts = this.db.getUnreadAlerts(client.sessionId);
    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'watchlist.alerts.fetch',
      payload: {
        alerts: alerts.map((a) => ({
          id: a.id,
          watchId: a.watch_id,
          alertType: a.alert_type,
          title: a.title,
          message: a.message,
          payload: JSON.parse(a.payload),
          createdAt: a.created_at,
        })),
      },
    });
  }

  // ── watchlist.alerts.markRead ──────────────────────────

  private handleWatchlistAlertsMarkRead(
    client: ConnectedClient,
    msg: WSMessage,
  ): void {
    if (!this.db) {
      this.sendTo(client.ws, {
        type: 'res',
        id: msg.id,
        method: 'watchlist.alerts.markRead',
        payload: { status: 'ok' },
      });
      return;
    }

    const result = WatchlistMarkReadSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid watchlist.alerts.markRead payload: ${result.error.message}`,
      );
      return;
    }

    if (result.data.all) {
      this.db.markAllAlertsRead(client.sessionId);
    } else if (result.data.alertIds) {
      for (const alertId of result.data.alertIds) {
        this.db.markAlertRead(alertId);
      }
    }

    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'watchlist.alerts.markRead',
      payload: { status: 'ok' },
    });
  }

  // ── credential.response ────────────────────────────────

  private handleCredentialResponse(
    client: ConnectedClient,
    msg: WSMessage,
  ): void {
    const result = CredentialResponseSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid credential.response payload: ${result.error.message}`,
      );
      return;
    }

    const { requestId } = result.data;

    // Clear pending timeout
    const pending = this.pendingCredentialRequests.get(requestId);
    if (pending) {
      clearTimeout(pending.timeoutId);
      this.pendingCredentialRequests.delete(requestId);
    }

    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent — no logging of payload (contains credentials)
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'credential/response',
      payload: result.data,
    });

    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'credential.response',
      payload: { status: 'sent' },
    });
  }

  // ── credential.none ───────────────────────────────────

  private handleCredentialNone(client: ConnectedClient, msg: WSMessage): void {
    const result = CredentialNoneSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid credential.none payload: ${result.error.message}`,
      );
      return;
    }

    const { requestId } = result.data;

    // Clear pending timeout
    const pending = this.pendingCredentialRequests.get(requestId);
    if (pending) {
      clearTimeout(pending.timeoutId);
      this.pendingCredentialRequests.delete(requestId);
    }

    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'credential/none',
      payload: result.data,
    });

    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'credential.none',
      payload: { status: 'sent' },
    });
  }

  // ── credential.tokenRefreshed ──────────────────────────

  private handleTokenRefreshed(client: ConnectedClient, msg: WSMessage): void {
    const result = OAuthTokenRefreshedSchema.safeParse(msg.payload);
    if (!result.success) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.VALIDATION_ERROR,
        `Invalid credential.tokenRefreshed payload: ${result.error.message}`,
      );
      return;
    }

    const { service, token, requestId } = result.data;

    // Clear pending refresh timeout if requestId provided
    if (requestId) {
      const pending = this.pendingTokenRefreshRequests.get(requestId);
      if (pending) {
        clearTimeout(pending.timeoutId);
        this.pendingTokenRefreshRequests.delete(requestId);
      }
    }

    // Update stored token
    this.oauthTokens.set(client.sessionId, {
      token,
      service,
      providedBy: client.deviceToken,
      receivedAt: new Date().toISOString(),
    });

    // Deliver refreshed token to agent
    const agentNode = this.findAgentNode(client.sessionId);
    if (!agentNode) {
      this.sendError(
        client.ws,
        msg.id,
        ErrorCodes.NO_AGENT,
        'No agent node connected to this session',
      );
      return;
    }

    // Forward to agent — no logging of token value
    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'credential/token',
      payload: {
        service,
        token,
        sessionId: client.sessionId,
      },
    });

    this.sendTo(client.ws, {
      type: 'res',
      id: msg.id,
      method: 'credential.tokenRefreshed',
      payload: { status: 'sent' },
    });

    log('info', 'oauth:token_refreshed', {
      sessionId: client.sessionId,
      service,
    });
  }

  // ── Lifecycle hooks (called by ws-server) ─────────────

  /** Called after successful handshake to handle OAuth token delivery */
  onClientConnected(client: ConnectedClient, payload: ConnectPayload): void {
    // Operator with Google OAuth token — store and try immediate delivery
    if (client.role === 'operator' && payload.googleOAuthToken) {
      const tokenValue = payload.googleOAuthToken.trim();
      if (tokenValue === '') {
        log('warn', 'oauth:empty_token_ignored', {
          sessionId: client.sessionId,
        });
        return;
      }

      const existing = this.oauthTokens.get(client.sessionId);
      if (existing) {
        log('warn', 'oauth:token_overwritten', {
          sessionId: client.sessionId,
          previousProvider: existing.providedBy,
        });
      }

      this.oauthTokens.set(client.sessionId, {
        token: tokenValue,
        service: 'google',
        providedBy: client.deviceToken,
        receivedAt: new Date().toISOString(),
      });

      log('info', 'oauth:token_stored', {
        sessionId: client.sessionId,
        service: 'google',
      });

      // Try to deliver if agent already in session
      this.tryDeliverOAuthToken(client.sessionId);
      return;
    }

    // Agent connecting — check for pending token to deliver
    if (client.role === 'node' && client.scopes.includes('agent')) {
      this.tryDeliverOAuthToken(client.sessionId);
    }
  }

  /** Called when a client disconnects — cleans up session-scoped tokens */
  onClientDisconnected(sessionId: string): void {
    const remainingClients = this.sessions.getSessionClients(sessionId);
    if (remainingClients.length === 0) {
      this.oauthTokens.delete(sessionId);

      // Clear any pending refresh timeouts for this session
      for (const [requestId, pending] of this.pendingTokenRefreshRequests) {
        if (pending.sessionId === sessionId) {
          clearTimeout(pending.timeoutId);
          this.pendingTokenRefreshRequests.delete(requestId);
        }
      }

      log('info', 'oauth:session_cleanup', { sessionId });
    }
  }

  /** Deliver stored OAuth token to the agent in a session, if both exist */
  private tryDeliverOAuthToken(sessionId: string): void {
    const tokenEntry = this.oauthTokens.get(sessionId);
    if (!tokenEntry) return;

    const agentNode = this.findAgentNode(sessionId);
    if (!agentNode) return;

    this.sendTo(agentNode.ws, {
      type: 'event',
      event: 'credential/token',
      payload: {
        service: tokenEntry.service,
        token: tokenEntry.token,
        sessionId,
      },
    });

    log('info', 'oauth:token_delivered', {
      sessionId,
      service: tokenEntry.service,
    });
  }

  // ── Helpers ──────────────────────────────────────────────

  private findAgentNode(sessionId: string): ConnectedClient | undefined {
    const nodes = this.sessions.getSessionClients(sessionId, { role: 'node' });
    return nodes.find((n) => n.scopes.includes('agent'));
  }

  private broadcastToOperators(sessionId: string, msg: WSMessage): void {
    const operators = this.sessions.getSessionClients(sessionId, {
      role: 'operator',
    });
    for (const op of operators) {
      this.sendTo(op.ws, msg);
    }
  }

  private sendTo(ws: WebSocket, msg: WSMessage): void {
    try {
      ws.send(JSON.stringify(msg));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Send failed';
      log('error', 'ws:send_error', { error: message });
    }
  }

  private sendError(
    ws: WebSocket,
    reqId: string | undefined,
    code: string,
    message: string,
  ): void {
    this.sendTo(ws, {
      type: 'res',
      id: reqId,
      payload: { error: code, message },
    });
  }
}
