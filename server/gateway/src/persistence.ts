import Database from 'better-sqlite3';
import type { Database as DatabaseType } from 'better-sqlite3';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const DEFAULT_DB_PATH = './data/gateway.db';

// ── Row types returned by queries ─────────────────────────────────

export interface SessionRow {
  id: string;
  created_at: string;
  last_activity: string;
  metadata: string;
}

export interface MessageRow {
  id: string;
  session_id: string;
  sender: string;
  content: string;
  timestamp: string;
}

export interface ApprovalRow {
  id: string;
  session_id: string;
  task_id: string;
  action: string;
  description: string;
  details: string;
  status: string;
  created_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
}

export interface AuditRow {
  id: string;
  task_id: string;
  action: string;
  decision: string;
  timestamp: string;
  context: string;
}

export interface CronJobRow {
  id: string;
  user_id: string;
  cron_expression: string;
  skill_name: string;
  task_description: string;
  payload: string;
  enabled: number;
  last_run: string | null;
  next_run: string | null;
  created_at: string;
}

export interface CronResultRow {
  id: string;
  job_id: string;
  status: string;
  result_data: string | null;
  previous_data: string | null;
  changed: number;
  executed_at: string;
}

export interface DeviceTokenRow {
  token: string;
  session_id: string;
  platform: string;
  registered_at: string;
  last_used: string;
}

// ── GatewayDB ─────────────────────────────────────────────────────

export class GatewayDB {
  readonly db: DatabaseType;

  constructor(dbPath: string = process.env.GATEWAY_DB_PATH ?? DEFAULT_DB_PATH) {
    // :memory: is valid and doesn't need a directory
    if (dbPath !== ':memory:') {
      mkdirSync(dirname(dbPath), { recursive: true });
    }

    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.db.pragma('foreign_keys = ON');

    this.migrate();
  }

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        last_activity TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}'
      );

      CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        sender TEXT NOT NULL CHECK (sender IN ('operator', 'agent', 'system')),
        content TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );
      CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp);

      CREATE TABLE IF NOT EXISTS processed_keys (
        session_id TEXT NOT NULL,
        key TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (session_id, key),
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        action TEXT NOT NULL,
        description TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending'
          CHECK (status IN ('pending', 'approved', 'denied', 'cancelled')),
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        resolved_by TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );
      CREATE INDEX IF NOT EXISTS idx_approvals_session ON approvals(session_id);
      CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

      CREATE TABLE IF NOT EXISTS audit_entries (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        action TEXT NOT NULL,
        decision TEXT NOT NULL
          CHECK (decision IN ('approved', 'denied', 'auto_allowed')),
        timestamp TEXT NOT NULL,
        context TEXT NOT NULL DEFAULT '{}'
      );
      CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_entries(task_id);

      CREATE TABLE IF NOT EXISTS cron_jobs (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        cron_expression TEXT NOT NULL,
        skill_name TEXT NOT NULL,
        task_description TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_run TEXT,
        next_run TEXT,
        created_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_cron_user ON cron_jobs(user_id);
      CREATE INDEX IF NOT EXISTS idx_cron_enabled ON cron_jobs(enabled);

      CREATE TABLE IF NOT EXISTS cron_results (
        id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('ok', 'error', 'skipped')),
        result_data TEXT,
        previous_data TEXT,
        changed INTEGER NOT NULL DEFAULT 0,
        executed_at TEXT NOT NULL,
        FOREIGN KEY (job_id) REFERENCES cron_jobs(id) ON DELETE CASCADE
      );
      CREATE INDEX IF NOT EXISTS idx_cron_results_job ON cron_results(job_id, executed_at);

      CREATE TABLE IF NOT EXISTS device_tokens (
        token TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT 'ios'
          CHECK (platform IN ('ios')),
        registered_at TEXT NOT NULL,
        last_used TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
      );
      CREATE INDEX IF NOT EXISTS idx_device_tokens_session ON device_tokens(session_id);
    `);
  }

  // ── Sessions ────────────────────────────────────────────────

  insertSession(id: string, createdAt: string, lastActivity: string): void {
    this.db
      .prepare(
        `INSERT OR REPLACE INTO sessions (id, created_at, last_activity) VALUES (?, ?, ?)`,
      )
      .run(id, createdAt, lastActivity);
  }

  updateSessionActivity(id: string, lastActivity: string): void {
    this.db
      .prepare(`UPDATE sessions SET last_activity = ? WHERE id = ?`)
      .run(lastActivity, id);
  }

  deleteSession(id: string): void {
    this.db.prepare(`DELETE FROM sessions WHERE id = ?`).run(id);
  }

  getSession(id: string): SessionRow | undefined {
    return this.db
      .prepare(
        `SELECT id, created_at, last_activity, metadata FROM sessions WHERE id = ?`,
      )
      .get(id) as SessionRow | undefined;
  }

  getAllSessions(): SessionRow[] {
    return this.db
      .prepare(`SELECT id, created_at, last_activity, metadata FROM sessions`)
      .all() as SessionRow[];
  }

  getActiveSessions(since: string): SessionRow[] {
    return this.db
      .prepare(
        `SELECT id, created_at, last_activity, metadata FROM sessions WHERE last_activity >= ?`,
      )
      .all(since) as SessionRow[];
  }

  pruneSessions(before: string): number {
    const result = this.db
      .prepare(`DELETE FROM sessions WHERE last_activity < ?`)
      .run(before);
    return result.changes;
  }

  // ── Messages ────────────────────────────────────────────────

  insertMessage(
    id: string,
    sessionId: string,
    sender: string,
    content: string,
    timestamp: string,
  ): void {
    this.db
      .prepare(
        `INSERT INTO messages (id, session_id, sender, content, timestamp) VALUES (?, ?, ?, ?, ?)`,
      )
      .run(id, sessionId, sender, content, timestamp);
  }

  getRecentMessages(sessionId: string, limit: number = 1000): MessageRow[] {
    return this.db
      .prepare(
        `SELECT id, session_id, sender, content, timestamp
       FROM messages WHERE session_id = ?
       ORDER BY timestamp ASC LIMIT ?`,
      )
      .all(sessionId, limit) as MessageRow[];
  }

  getMessageCount(sessionId: string): number {
    const row = this.db
      .prepare(`SELECT COUNT(*) as count FROM messages WHERE session_id = ?`)
      .get(sessionId) as { count: number };
    return row.count;
  }

  // ── Processed Keys ──────────────────────────────────────────

  insertProcessedKey(sessionId: string, key: string): void {
    this.db
      .prepare(
        `INSERT OR IGNORE INTO processed_keys (session_id, key) VALUES (?, ?)`,
      )
      .run(sessionId, key);
  }

  hasProcessedKey(sessionId: string, key: string): boolean {
    const row = this.db
      .prepare(`SELECT 1 FROM processed_keys WHERE session_id = ? AND key = ?`)
      .get(sessionId, key);
    return row !== undefined;
  }

  getProcessedKeys(sessionId: string): string[] {
    const rows = this.db
      .prepare(`SELECT key FROM processed_keys WHERE session_id = ?`)
      .all(sessionId) as Array<{ key: string }>;
    return rows.map((r) => r.key);
  }

  // ── Approvals ───────────────────────────────────────────────

  insertApproval(
    id: string,
    sessionId: string,
    taskId: string,
    action: string,
    description: string,
    details: string,
    createdAt: string,
  ): void {
    this.db
      .prepare(
        `INSERT INTO approvals (id, session_id, task_id, action, description, details, status, created_at)
       VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)`,
      )
      .run(id, sessionId, taskId, action, description, details, createdAt);
  }

  resolveApproval(
    id: string,
    status: 'approved' | 'denied' | 'cancelled',
    resolvedBy?: string,
  ): void {
    this.db
      .prepare(
        `UPDATE approvals SET status = ?, resolved_at = ?, resolved_by = ? WHERE id = ?`,
      )
      .run(status, new Date().toISOString(), resolvedBy ?? null, id);
  }

  getPendingApprovals(): ApprovalRow[] {
    return this.db
      .prepare(
        `SELECT id, session_id, task_id, action, description, details, status, created_at, resolved_at, resolved_by
       FROM approvals WHERE status = 'pending'`,
      )
      .all() as ApprovalRow[];
  }

  getApproval(id: string): ApprovalRow | undefined {
    return this.db
      .prepare(
        `SELECT id, session_id, task_id, action, description, details, status, created_at, resolved_at, resolved_by
       FROM approvals WHERE id = ?`,
      )
      .get(id) as ApprovalRow | undefined;
  }

  getResolvedApprovals(sessionId?: string): ApprovalRow[] {
    if (sessionId) {
      return this.db
        .prepare(
          `SELECT * FROM approvals WHERE status != 'pending' AND session_id = ?`,
        )
        .all(sessionId) as ApprovalRow[];
    }
    return this.db
      .prepare(`SELECT * FROM approvals WHERE status != 'pending'`)
      .all() as ApprovalRow[];
  }

  // ── Audit Entries ───────────────────────────────────────────

  insertAuditEntry(
    id: string,
    taskId: string,
    action: string,
    decision: string,
    timestamp: string,
    context: string,
  ): void {
    this.db
      .prepare(
        `INSERT INTO audit_entries (id, task_id, action, decision, timestamp, context)
       VALUES (?, ?, ?, ?, ?, ?)`,
      )
      .run(id, taskId, action, decision, timestamp, context);
  }

  getAuditLog(taskId?: string): AuditRow[] {
    if (taskId) {
      return this.db
        .prepare(
          `SELECT * FROM audit_entries WHERE task_id = ? ORDER BY timestamp ASC`,
        )
        .all(taskId) as AuditRow[];
    }
    return this.db
      .prepare(`SELECT * FROM audit_entries ORDER BY timestamp ASC`)
      .all() as AuditRow[];
  }

  getAuditEntry(id: string): AuditRow | undefined {
    return this.db
      .prepare(`SELECT * FROM audit_entries WHERE id = ?`)
      .get(id) as AuditRow | undefined;
  }

  getAuditByAction(action: string): AuditRow[] {
    return this.db
      .prepare(
        `SELECT * FROM audit_entries WHERE action = ? ORDER BY timestamp ASC`,
      )
      .all(action) as AuditRow[];
  }

  getAuditByDecision(decision: string): AuditRow[] {
    return this.db
      .prepare(
        `SELECT * FROM audit_entries WHERE decision = ? ORDER BY timestamp ASC`,
      )
      .all(decision) as AuditRow[];
  }

  getAuditSummary(): {
    total: number;
    approved: number;
    denied: number;
    autoAllowed: number;
  } {
    const rows = this.db
      .prepare(
        `SELECT decision, COUNT(*) as count FROM audit_entries GROUP BY decision`,
      )
      .all() as Array<{ decision: string; count: number }>;
    const summary = { total: 0, approved: 0, denied: 0, autoAllowed: 0 };
    for (const r of rows) {
      summary.total += r.count;
      if (r.decision === 'approved') summary.approved = r.count;
      else if (r.decision === 'denied') summary.denied = r.count;
      else if (r.decision === 'auto_allowed') summary.autoAllowed = r.count;
    }
    return summary;
  }

  clearAuditLog(): void {
    this.db.prepare(`DELETE FROM audit_entries`).run();
  }

  // ── Cron Jobs ───────────────────────────────────────────────

  insertCronJob(
    id: string,
    userId: string,
    cronExpression: string,
    skillName: string,
    taskDescription: string,
    payload: string,
    createdAt: string,
  ): void {
    this.db
      .prepare(
        `INSERT INTO cron_jobs (id, user_id, cron_expression, skill_name, task_description, payload, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        id,
        userId,
        cronExpression,
        skillName,
        taskDescription,
        payload,
        createdAt,
      );
  }

  getEnabledCronJobs(): CronJobRow[] {
    return this.db
      .prepare(`SELECT * FROM cron_jobs WHERE enabled = 1`)
      .all() as CronJobRow[];
  }

  updateCronJobRun(id: string, lastRun: string, nextRun: string): void {
    this.db
      .prepare(`UPDATE cron_jobs SET last_run = ?, next_run = ? WHERE id = ?`)
      .run(lastRun, nextRun, id);
  }

  disableCronJob(id: string): void {
    this.db.prepare(`UPDATE cron_jobs SET enabled = 0 WHERE id = ?`).run(id);
  }

  enableCronJob(id: string): void {
    this.db.prepare(`UPDATE cron_jobs SET enabled = 1 WHERE id = ?`).run(id);
  }

  getCronJob(id: string): CronJobRow | undefined {
    return this.db.prepare(`SELECT * FROM cron_jobs WHERE id = ?`).get(id) as
      | CronJobRow
      | undefined;
  }

  getUserCronJobs(userId: string): CronJobRow[] {
    return this.db
      .prepare(
        `SELECT * FROM cron_jobs WHERE user_id = ? ORDER BY created_at DESC`,
      )
      .all(userId) as CronJobRow[];
  }

  deleteCronJob(id: string): void {
    this.db.prepare(`DELETE FROM cron_jobs WHERE id = ?`).run(id);
  }

  // ── Cron Results ──────────────────────────────────────────

  insertCronResult(
    id: string,
    jobId: string,
    status: string,
    resultData: string | null,
    previousData: string | null,
    changed: boolean,
    executedAt: string,
  ): void {
    this.db
      .prepare(
        `INSERT INTO cron_results (id, job_id, status, result_data, previous_data, changed, executed_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        id,
        jobId,
        status,
        resultData,
        previousData,
        changed ? 1 : 0,
        executedAt,
      );
  }

  getLatestResult(jobId: string): CronResultRow | undefined {
    return this.db
      .prepare(
        `SELECT * FROM cron_results WHERE job_id = ? ORDER BY executed_at DESC LIMIT 1`,
      )
      .get(jobId) as CronResultRow | undefined;
  }

  getResultHistory(jobId: string, limit: number = 20): CronResultRow[] {
    return this.db
      .prepare(
        `SELECT * FROM cron_results WHERE job_id = ? ORDER BY executed_at DESC LIMIT ?`,
      )
      .all(jobId, limit) as CronResultRow[];
  }

  // ── Device Tokens ──────────────────────────────────────────

  registerDeviceToken(
    token: string,
    sessionId: string,
    platform: string = 'ios',
  ): void {
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO device_tokens (token, session_id, platform, registered_at, last_used)
       VALUES (?, ?, ?, ?, ?)
       ON CONFLICT(token) DO UPDATE SET session_id = ?, last_used = ?`,
      )
      .run(token, sessionId, platform, now, now, sessionId, now);
  }

  unregisterDeviceToken(token: string): void {
    this.db.prepare(`DELETE FROM device_tokens WHERE token = ?`).run(token);
  }

  getDeviceTokensForSession(sessionId: string): DeviceTokenRow[] {
    return this.db
      .prepare(
        `SELECT token, session_id, platform, registered_at, last_used
       FROM device_tokens WHERE session_id = ?`,
      )
      .all(sessionId) as DeviceTokenRow[];
  }

  removeStaleTokens(before: string): number {
    const result = this.db
      .prepare(`DELETE FROM device_tokens WHERE last_used < ?`)
      .run(before);
    return result.changes;
  }

  // ── Lifecycle ───────────────────────────────────────────────

  close(): void {
    this.db.close();
  }
}
