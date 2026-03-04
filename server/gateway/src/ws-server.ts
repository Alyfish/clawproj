import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from 'node:http';
import { WebSocketServer, WebSocket } from 'ws';
import { v4 as uuidv4 } from 'uuid';
import { z } from 'zod';
import SessionManager from './session-manager.js';
import MessageRouter from './message-router.js';
import { GatewayDB } from './persistence.js';
import type {
  ClientRole,
  ConnectedClient,
  ConnectPayload,
  PushHookFn,
  WSMessage,
} from './types.js';

const HANDSHAKE_TIMEOUT_MS = 10_000;

const ConnectPayloadSchema = z.object({
  role: z.enum(['operator', 'node']),
  scopes: z.array(z.string()),
  authToken: z.string().optional(),
  sessionId: z.string().optional(),
  deviceToken: z.string().optional(),
});

function log(
  level: 'info' | 'warn' | 'error',
  event: string,
  data?: Record<string, unknown>,
): void {
  console.log(
    JSON.stringify({ level, event, data, timestamp: new Date().toISOString() }),
  );
}

export interface GatewayServerOptions {
  port: number;
  dbPath?: string;
}

export default class GatewayServer {
  private httpServer: ReturnType<typeof createServer>;
  private wss: WebSocketServer;
  private sessionManager: SessionManager;
  private gatewayDb: GatewayDB;
  private router: MessageRouter;
  private connections: Map<string, ConnectedClient> = new Map();
  private startTime: number = Date.now();

  /** Pluggable message handler — set via setMessageHandler() */
  private messageHandler:
    | ((client: ConnectedClient, raw: string) => void)
    | null = null;

  /** Pluggable test-push endpoint handler */
  private testPushHandler:
    | ((body: string, res: ServerResponse) => void)
    | null = null;

  private readonly port: number;

  constructor(options: GatewayServerOptions) {
    this.port = options.port;

    // Initialize persistence
    this.gatewayDb = new GatewayDB(options.dbPath);

    // Pass DB to session manager for write-through persistence
    this.sessionManager = new SessionManager(this.gatewayDb);

    // Wire up the message router
    this.router = new MessageRouter(this.sessionManager);
    this.setMessageHandler((client, raw) =>
      this.router.handleMessage(client, raw),
    );

    // HTTP server with /health endpoint
    this.httpServer = createServer(
      (req: IncomingMessage, res: ServerResponse) => {
        if (req.method === 'GET' && req.url === '/health') {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(
            JSON.stringify({
              status: 'ok',
              connections: this.connections.size,
              sessions: this.sessionManager.listSessions().length,
              uptime: Math.floor((Date.now() - this.startTime) / 1000),
            }),
          );
        } else if (req.method === 'POST' && req.url === '/api/test-push') {
          let body = '';
          req.on('data', (chunk: Buffer) => {
            body += chunk.toString();
          });
          req.on('end', () => {
            if (this.testPushHandler) {
              this.testPushHandler(body, res);
            } else {
              res.writeHead(501, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ error: 'Push not configured' }));
            }
          });
        } else {
          res.writeHead(404);
          res.end();
        }
      },
    );

    // WebSocket server attached to HTTP server
    this.wss = new WebSocketServer({ server: this.httpServer });
    this.wss.on('connection', (ws, req) => this.handleConnection(ws, req));
  }

  /**
   * Plug in a message handler for post-handshake messages.
   * The router module calls this to attach itself.
   */
  setMessageHandler(
    handler: (client: ConnectedClient, raw: string) => void,
  ): void {
    this.messageHandler = handler;
  }

  getSessionManager(): SessionManager {
    return this.sessionManager;
  }

  getDB(): GatewayDB {
    return this.gatewayDb;
  }

  getRouter(): MessageRouter {
    return this.router;
  }

  getConnections(): Map<string, ConnectedClient> {
    return this.connections;
  }

  /** Reconfigure the message router with DB and push hook. */
  configureRouter(db: GatewayDB, pushHook?: PushHookFn): void {
    this.router = new MessageRouter(
      this.sessionManager,
      undefined,
      pushHook,
      db,
    );
    this.setMessageHandler((client, raw) =>
      this.router.handleMessage(client, raw),
    );
  }

  setTestPushHandler(
    handler: (body: string, res: ServerResponse) => void,
  ): void {
    this.testPushHandler = handler;
  }

  async start(): Promise<void> {
    return new Promise((resolve) => {
      this.httpServer.listen(this.port, () => {
        log('info', 'gateway:listening', { port: this.port });
        resolve();
      });
    });
  }

  async stop(): Promise<void> {
    // Close all WebSocket connections gracefully
    for (const client of this.connections.values()) {
      client.ws.close(1001, 'Server shutting down');
    }
    this.connections.clear();

    // Close WebSocket server
    await new Promise<void>((resolve) => {
      this.wss.close(() => resolve());
    });

    // Close HTTP server
    await new Promise<void>((resolve, reject) => {
      this.httpServer.close((err) => (err ? reject(err) : resolve()));
    });

    this.sessionManager.destroy();
    this.gatewayDb.close();
    log('info', 'gateway:stopped');
  }

  // ── Connection lifecycle ──────────────────────────────────────

  private handleConnection(ws: WebSocket, _req: IncomingMessage): void {
    let handshakeCompleted = false;

    // 10s timeout for handshake
    const timeout = setTimeout(() => {
      if (!handshakeCompleted) {
        log('warn', 'client:handshake_timeout');
        ws.close(4001, 'Handshake timeout');
      }
    }, HANDSHAKE_TIMEOUT_MS);

    // First message must be the connect handshake
    ws.once('message', (data) => {
      clearTimeout(timeout);
      handshakeCompleted = true;

      try {
        this.performHandshake(ws, data.toString());
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Handshake failed';
        log('error', 'client:handshake_error', { error: message });
        this.sendRaw(ws, {
          type: 'res',
          method: 'connect',
          payload: { error: 'HANDSHAKE_ERROR', message },
        });
        ws.close(4002, message);
      }
    });

    ws.on('error', (err) => {
      log('error', 'ws:error', { error: err.message });
    });
  }

  private performHandshake(ws: WebSocket, raw: string): void {
    // Parse the incoming message
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      throw new Error('Invalid JSON in handshake');
    }

    // Validate it's a connect request
    const msg = parsed as WSMessage;
    if (msg.type !== 'req' || msg.method !== 'connect') {
      throw new Error('First message must be a connect request');
    }

    // Validate the payload
    const payloadResult = ConnectPayloadSchema.safeParse(msg.payload);
    if (!payloadResult.success) {
      throw new Error(
        `Invalid connect payload: ${payloadResult.error.message}`,
      );
    }
    const payload: ConnectPayload = payloadResult.data;

    // Auth check placeholder — just log whether token was provided
    if (payload.authToken) {
      log('info', 'client:auth_token_provided');
      // TODO: Validate JWT or API key
    } else {
      log('info', 'client:no_auth_token');
    }

    let deviceToken: string;
    let sessionId: string;

    // Try reconnection if deviceToken provided
    if (payload.deviceToken) {
      const reconnectResult = this.sessionManager.tryReconnect(
        payload.deviceToken,
      );
      if (reconnectResult) {
        deviceToken = payload.deviceToken;
        sessionId = reconnectResult.session.id;
        log('info', 'client:reconnected', { deviceToken, sessionId });
      } else {
        // Reconnect failed — treat as new connection
        deviceToken = uuidv4();
        sessionId = this.resolveSessionId(payload.sessionId, payload.role);
      }
    } else {
      deviceToken = uuidv4();
      sessionId = this.resolveSessionId(payload.sessionId, payload.role);
    }

    const now = new Date().toISOString();
    const client: ConnectedClient = {
      ws,
      deviceToken,
      role: payload.role,
      scopes: payload.scopes,
      sessionId,
      connectedAt: now,
      lastSeen: now,
    };

    // Register client
    this.sessionManager.addClient(sessionId, client);
    this.connections.set(deviceToken, client);

    // Wire up post-handshake message handler
    ws.on('message', (data) => {
      client.lastSeen = new Date().toISOString();
      const rawMsg = data.toString();

      if (this.messageHandler) {
        this.messageHandler(client, rawMsg);
      } else {
        // Stub: just log until router is plugged in
        log('info', 'message:received', {
          deviceToken: client.deviceToken,
          raw: rawMsg.slice(0, 200),
        });
      }
    });

    // Wire up disconnect handler
    ws.on('close', () => this.handleDisconnect(client));

    // Send connect response
    this.sendRaw(ws, {
      type: 'res',
      id: msg.id,
      method: 'connect',
      payload: { deviceToken, sessionId },
    });

    log('info', 'client:connected', {
      deviceToken,
      role: payload.role,
      sessionId,
      scopes: payload.scopes,
    });
  }

  private resolveSessionId(
    requestedSessionId?: string,
    role?: ClientRole,
  ): string {
    if (requestedSessionId) {
      const existing = this.sessionManager.getSession(requestedSessionId);
      if (existing) {
        return existing.id;
      }
      log('warn', 'session:not_found', {
        requestedSessionId,
        action: 'creating_new',
      });
    }
    // Auto-join: find a session with the complementary role
    if (role) {
      const match = this.sessionManager.findSessionForRole(role);
      if (match) {
        log('info', 'session:auto_joined', { sessionId: match.id, role });
        return match.id;
      }
    }
    return this.sessionManager.createSession().id;
  }

  private handleDisconnect(client: ConnectedClient): void {
    this.connections.delete(client.deviceToken);
    this.sessionManager.removeClient(client.deviceToken, client.sessionId);

    log('info', 'client:disconnected', {
      deviceToken: client.deviceToken,
      role: client.role,
      sessionId: client.sessionId,
    });

    // If an agent node disconnected, notify operators in the session
    if (client.role === 'node') {
      const operators = this.sessionManager.getSessionClients(
        client.sessionId,
        { role: 'operator' },
      );
      const notification: WSMessage = {
        type: 'event',
        event: 'agent/disconnected',
        payload: {
          sessionId: client.sessionId,
          timestamp: new Date().toISOString(),
        },
      };
      for (const op of operators) {
        this.sendRaw(op.ws, notification);
      }
    }
  }

  private sendRaw(ws: WebSocket, msg: WSMessage): void {
    try {
      ws.send(JSON.stringify(msg));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Send failed';
      log('error', 'ws:send_error', { error: message });
    }
  }
}
