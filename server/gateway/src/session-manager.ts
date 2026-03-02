import { v4 as uuidv4 } from 'uuid';
import type {
  Session,
  ConnectedClient,
  DisconnectedClient,
  MessageHistoryEntry,
  ClientRole,
} from './types.js';

const RECONNECT_WINDOW_MS = 30_000;
const CLEANUP_INTERVAL_MS = 10_000;
const MAX_HISTORY_ENTRIES = 1_000;

function log(
  level: 'info' | 'warn' | 'error',
  event: string,
  data?: Record<string, unknown>,
): void {
  console.log(
    JSON.stringify({ level, event, data, timestamp: new Date().toISOString() }),
  );
}

export default class SessionManager {
  // TODO: Replace with Redis/DB for persistence
  private sessions: Map<string, Session> = new Map();
  // TODO: Replace with Redis/DB for persistence
  private disconnectedClients: Map<string, DisconnectedClient> = new Map();
  private cleanupTimer: ReturnType<typeof setInterval>;

  constructor() {
    this.cleanupTimer = setInterval(
      () => this.cleanupExpiredDisconnects(),
      CLEANUP_INTERVAL_MS,
    );
  }

  createSession(): Session {
    const id = uuidv4();
    const now = new Date().toISOString();
    const session: Session = {
      id,
      clients: new Map(),
      history: [],
      processedKeys: new Set(),
      createdAt: now,
      lastActivity: now,
    };
    this.sessions.set(id, session);
    log('info', 'session:created', { sessionId: id });
    return session;
  }

  getSession(id: string): Session | undefined {
    return this.sessions.get(id);
  }

  listSessions(): Session[] {
    return Array.from(this.sessions.values());
  }

  addClient(sessionId: string, client: ConnectedClient): void {
    const session = this.sessions.get(sessionId);
    if (!session) {
      throw new Error(`Session ${sessionId} not found`);
    }
    session.clients.set(client.deviceToken, client);
    session.lastActivity = new Date().toISOString();

    // Clear from disconnected pool if present (successful reconnect)
    this.disconnectedClients.delete(client.deviceToken);
  }

  removeClient(deviceToken: string, sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (!session) return;

    const client = session.clients.get(deviceToken);
    if (!client) return;

    session.clients.delete(deviceToken);

    // Move to disconnected pool for potential reconnection
    this.disconnectedClients.set(deviceToken, {
      deviceToken,
      role: client.role,
      scopes: client.scopes,
      sessionId,
      disconnectedAt: new Date().toISOString(),
    });
  }

  tryReconnect(deviceToken: string): {
    session: Session;
    previousScopes: string[];
    previousRole: ClientRole;
  } | null {
    const disconnected = this.disconnectedClients.get(deviceToken);
    if (!disconnected) return null;

    const elapsed =
      Date.now() - new Date(disconnected.disconnectedAt).getTime();
    if (elapsed >= RECONNECT_WINDOW_MS) {
      this.disconnectedClients.delete(deviceToken);
      return null;
    }

    const session = this.sessions.get(disconnected.sessionId);
    if (!session) {
      this.disconnectedClients.delete(deviceToken);
      return null;
    }

    // Remove from disconnected pool — caller will re-add as connected
    this.disconnectedClients.delete(deviceToken);

    log('info', 'client:reconnected', {
      deviceToken,
      sessionId: session.id,
    });

    return {
      session,
      previousScopes: disconnected.scopes,
      previousRole: disconnected.role,
    };
  }

  addHistory(sessionId: string, entry: MessageHistoryEntry): void {
    const session = this.sessions.get(sessionId);
    if (!session) return;

    session.history.push(entry);
    session.lastActivity = new Date().toISOString();

    // Cap at MAX_HISTORY_ENTRIES — remove oldest
    while (session.history.length > MAX_HISTORY_ENTRIES) {
      session.history.shift();
    }
  }

  getHistory(sessionId: string): MessageHistoryEntry[] {
    const session = this.sessions.get(sessionId);
    return session ? session.history : [];
  }

  hasProcessedKey(sessionId: string, key: string): boolean {
    const session = this.sessions.get(sessionId);
    return session ? session.processedKeys.has(key) : false;
  }

  markKeyProcessed(sessionId: string, key: string): void {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.processedKeys.add(key);
    }
  }

  getSessionClients(
    sessionId: string,
    filter?: { role?: ClientRole },
  ): ConnectedClient[] {
    const session = this.sessions.get(sessionId);
    if (!session) return [];

    const clients = Array.from(session.clients.values());
    if (filter?.role) {
      return clients.filter((c) => c.role === filter.role);
    }
    return clients;
  }

  cleanupExpiredDisconnects(): void {
    const now = Date.now();
    for (const [token, entry] of this.disconnectedClients) {
      const elapsed = now - new Date(entry.disconnectedAt).getTime();
      if (elapsed >= RECONNECT_WINDOW_MS) {
        this.disconnectedClients.delete(token);
        log('info', 'disconnect:expired', { deviceToken: token });
      }
    }

    // Clean up sessions with no connected clients and no pending reconnects
    for (const [id, session] of this.sessions) {
      if (session.clients.size > 0) continue;

      const hasPendingReconnect = Array.from(
        this.disconnectedClients.values(),
      ).some((d) => d.sessionId === id);

      if (!hasPendingReconnect) {
        this.sessions.delete(id);
        log('info', 'session:expired', { sessionId: id });
      }
    }
  }

  destroy(): void {
    clearInterval(this.cleanupTimer);
  }
}
