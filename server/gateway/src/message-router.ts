import { v4 as uuidv4 } from 'uuid';
import { z } from 'zod';
import type { WebSocket } from 'ws';
import type {
  ConnectedClient,
  WSMessage,
  MessageHistoryEntry,
  ApprovalHookFn,
} from './types.js';
import SessionManager from './session-manager.js';

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

const WSMessageSchema = z.object({
  type: z.enum(['req', 'res', 'event']),
  id: z.string().optional(),
  method: z.string().optional(),
  event: z.string().optional(),
  payload: z.any().optional(),
});

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

  constructor(sessions: SessionManager, approvalHook?: ApprovalHookFn) {
    this.sessions = sessions;
    this.approvalHook = approvalHook ?? (async () => {});
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

    // Broadcast to all operators in the session
    this.broadcastToOperators(client.sessionId, msg);

    // Skip history for ephemeral browser login frames (~80KB each)
    if ((msg.event ?? '').startsWith('browser/login:')) {
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
