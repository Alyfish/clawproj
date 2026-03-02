import { chromium, Browser, BrowserContext, Page } from 'playwright';

// ── Types ────────────────────────────────────────────────────────────

interface BrowserSession {
  id: string;
  context: BrowserContext;
  page: Page;
  createdAt: number;
  lastActivity: number;
}

// ── Constants ────────────────────────────────────────────────────────

const MAX_CONCURRENT_SESSIONS = 3;
const SESSION_TIMEOUT_MS = 10 * 60 * 1000; // 10 minutes
const CLEANUP_INTERVAL_MS = 60 * 1000; // 1 minute
const VIEWPORT = { width: 1280, height: 720 };

// ── Logging ──────────────────────────────────────────────────────────

function log(
  level: 'info' | 'warn' | 'error',
  event: string,
  data?: Record<string, unknown>,
): void {
  console.log(
    JSON.stringify({ level, event, data, timestamp: new Date().toISOString() }),
  );
}

// ── SessionManager ───────────────────────────────────────────────────

export class SessionManager {
  private browser: Browser | null = null;
  private sessions: Map<string, BrowserSession> = new Map();
  private cleanupTimer: ReturnType<typeof setInterval> | null = null;

  async initialize(): Promise<void> {
    this.browser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
      ],
    });

    this.cleanupTimer = setInterval(() => {
      this.cleanupStaleSessions().catch((e) =>
        log('error', 'session:cleanup_error', { error: String(e) }),
      );
    }, CLEANUP_INTERVAL_MS);

    log('info', 'browser:launched');
  }

  async getOrCreateSession(
    sessionId: string,
  ): Promise<{ context: BrowserContext; page: Page }> {
    // Return existing session if found
    const existing = this.sessions.get(sessionId);
    if (existing) {
      existing.lastActivity = Date.now();
      return { context: existing.context, page: existing.page };
    }

    // Evict oldest if at capacity
    if (this.sessions.size >= MAX_CONCURRENT_SESSIONS) {
      let oldestId: string | null = null;
      let oldestActivity = Infinity;

      for (const [id, session] of this.sessions) {
        if (session.lastActivity < oldestActivity) {
          oldestActivity = session.lastActivity;
          oldestId = id;
        }
      }

      if (oldestId) {
        await this.closeSession(oldestId);
        log('info', 'session:evicted', {
          sessionId: oldestId,
          reason: 'max_concurrent',
        });
      }
    }

    // Lazy-init browser
    if (!this.browser) {
      await this.initialize();
    }

    // Create isolated context + page
    const context = await this.browser!.newContext({
      viewport: VIEWPORT,
      ignoreHTTPSErrors: true,
    });

    const page = await context.newPage();
    page.setDefaultTimeout(10_000);
    page.setDefaultNavigationTimeout(30_000);

    const now = Date.now();
    const session: BrowserSession = {
      id: sessionId,
      context,
      page,
      createdAt: now,
      lastActivity: now,
    };

    this.sessions.set(sessionId, session);
    log('info', 'session:created', {
      sessionId,
      totalSessions: this.sessions.size,
    });

    return { context, page };
  }

  async closeSession(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) return;

    try {
      await session.context.close();
    } catch {
      // Context may already be closed — always remove from map
    }

    this.sessions.delete(sessionId);
    log('info', 'session:closed', { sessionId });
  }

  async takeScreenshot(sessionId: string): Promise<string> {
    const session = this.sessions.get(sessionId);
    if (!session) return '';

    try {
      const buffer = await session.page.screenshot({
        type: 'png',
        fullPage: false,
      });
      return buffer.toString('base64');
    } catch {
      return '';
    }
  }

  getPage(sessionId: string): Page | null {
    const session = this.sessions.get(sessionId);
    if (!session) return null;

    session.lastActivity = Date.now();
    return session.page;
  }

  private async cleanupStaleSessions(): Promise<void> {
    const now = Date.now();

    for (const [id, session] of this.sessions) {
      if (now - session.lastActivity > SESSION_TIMEOUT_MS) {
        try {
          await session.context.close();
        } catch {
          // Already closed
        }

        this.sessions.delete(id);
        log('info', 'session:timeout', { sessionId: id });
      }
    }
  }

  async shutdown(): Promise<void> {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer);
      this.cleanupTimer = null;
    }

    for (const [id] of this.sessions) {
      await this.closeSession(id);
    }

    if (this.browser) {
      await this.browser.close();
      this.browser = null;
    }

    log('info', 'browser:shutdown');
  }

  getStatus(): { activeSessions: number; sessionIds: string[] } {
    return {
      activeSessions: this.sessions.size,
      sessionIds: Array.from(this.sessions.keys()),
    };
  }
}
