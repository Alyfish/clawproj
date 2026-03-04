import { v4 as uuidv4 } from 'uuid';
import type {
  Session,
  ConnectedClient,
  DisconnectedClient,
  MessageHistoryEntry,
  ClientRole,
} from './types.js';
import type { GatewayDB } from './persistence.js';

const RECONNECT_WINDOW_MS = 30_000;
const CLEANUP_INTERVAL_MS = 10_000;
const MAX_HISTORY_ENTRIES = 1_000;
const ACTIVITY_DEBOUNCE_MS = 60_000;
const SESSION_RETENTION_MS = 24 * 60 * 60 * 1000; // 24h

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
  private sessions: Map<string, Session> = new Map();
  private disconnectedClients: Map<string, DisconnectedClient> = new Map();
  private cleanupTimer: ReturnType<typeof setInterval>;
  private activityTimers: Map<string, ReturnType<typeof setTimeout>> =
    new Map();
  private db: GatewayDB | null;

  constructor(db?: GatewayDB) {
    this.db = db ?? null;

    // Rehydrate sessions from SQLite on startup
    if (this.db) {
      this.rehydrate();
    }

    this.cleanupTimer = setInterval(
      () => this.cleanupExpiredDisconnects(),
      CLEANUP_INTERVAL_MS,
    );
  }

  private rehydrate(): void {
    if (!this.db) return;

    const since = new Date(Date.now() - SESSION_RETENTION_MS).toISOString();
    const dbSessions = this.db.getActiveSessions(since);

    for (const row of dbSessions) {
      const dbMessages = this.db.getRecentMessages(row.id, MAX_HISTORY_ENTRIES);
      const history: MessageHistoryEntry[] = dbMessages.map((m) => ({
        id: m.id,
        sessionId: m.session_id,
        sender: m.sender as 'operator' | 'agent' | 'system',
        message: JSON.parse(m.content),
        timestamp: m.timestamp,
      }));

      const dbKeys = this.db.getProcessedKeys(row.id);

      const session: Session = {
        id: row.id,
        clients: new Map(),
        history,
        processedKeys: new Set(dbKeys),
        createdAt: row.created_at,
        lastActivity: row.last_activity,
      };
      this.sessions.set(row.id, session);
    }

    log('info', 'sessions:rehydrated', { count: dbSessions.length });
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

    // Write-through to SQLite
    this.db?.insertSession(id, now, now);

    log('info', 'session:created', { sessionId: id });
    return session;
  }

  getSession(id: string): Session | undefined {
    const cached = this.sessions.get(id);
    if (cached) return cached;

    // Cache miss — try rehydrating from SQLite
    if (!this.db) return undefined;
    const row = this.db.getSession(id);
    if (!row) return undefined;

    const dbMessages = this.db.getRecentMessages(id, MAX_HISTORY_ENTRIES);
    const history: MessageHistoryEntry[] = dbMessages.map((m) => ({
      id: m.id,
      sessionId: m.session_id,
      sender: m.sender as 'operator' | 'agent' | 'system',
      message: JSON.parse(m.content),
      timestamp: m.timestamp,
    }));
    const dbKeys = this.db.getProcessedKeys(id);

    const session: Session = {
      id: row.id,
      clients: new Map(),
      history,
      processedKeys: new Set(dbKeys),
      createdAt: row.created_at,
      lastActivity: row.last_activity,
    };
    this.sessions.set(id, session);
    return session;
  }

  findSessionForRole(role: ClientRole): Session | undefined {
    const complementary = role === 'node' ? 'operator' : 'node';
    let best: Session | undefined;
    for (const session of this.sessions.values()) {
      const hasComplement = Array.from(session.clients.values()).some(
        (c) => c.role === complementary,
      );
      if (hasComplement) {
        if (!best || session.lastActivity > best.lastActivity) {
          best = session;
        }
      }
    }
    return best;
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

    // Debounced activity write
    this.debouncedActivityUpdate(sessionId, session.lastActivity);
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

    // Write-through to SQLite
    this.db?.insertMessage(
      entry.id,
      entry.sessionId,
      entry.sender,
      JSON.stringify(entry.message),
      entry.timestamp,
    );

    // Cap at MAX_HISTORY_ENTRIES in memory (DB keeps all)
    while (session.history.length > MAX_HISTORY_ENTRIES) {
      session.history.shift();
    }

    // Debounced activity write
    this.debouncedActivityUpdate(sessionId, session.lastActivity);
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
      this.db?.insertProcessedKey(sessionId, key);
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

    // Evict from in-memory cache only — SQLite retains for rehydration
    for (const [id, session] of this.sessions) {
      if (session.clients.size > 0) continue;

      const hasPendingReconnect = Array.from(
        this.disconnectedClients.values(),
      ).some((d) => d.sessionId === id);

      if (!hasPendingReconnect) {
        this.sessions.delete(id);
        log('info', 'session:evicted_from_cache', { sessionId: id });
      }
    }
  }

  private debouncedActivityUpdate(sessionId: string, timestamp: string): void {
    if (!this.db) return;

    const existing = this.activityTimers.get(sessionId);
    if (existing) clearTimeout(existing);

    const timer = setTimeout(() => {
      this.db?.updateSessionActivity(sessionId, timestamp);
      this.activityTimers.delete(sessionId);
    }, ACTIVITY_DEBOUNCE_MS);

    this.activityTimers.set(sessionId, timer);
  }

  destroy(): void {
    clearInterval(this.cleanupTimer);

    // Flush pending debounced activity updates
    for (const [sessionId, timer] of this.activityTimers) {
      clearTimeout(timer);
      const session = this.sessions.get(sessionId);
      if (session) {
        this.db?.updateSessionActivity(sessionId, session.lastActivity);
      }
    }
    this.activityTimers.clear();
  }
}
