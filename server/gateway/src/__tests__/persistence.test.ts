import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { unlinkSync } from 'node:fs';
import { GatewayDB } from '../persistence.js';
import SessionManager from '../session-manager.js';

// ── GatewayDB unit tests ──────────────────────────────────────────

describe('GatewayDB', () => {
  let db: GatewayDB;

  beforeEach(() => {
    db = new GatewayDB(':memory:');
  });

  afterEach(() => {
    db.close();
  });

  // ── Table creation ──────────────────────────────────────────

  it('creates all tables on construction', () => {
    const tables = db.db
      .prepare(
        `SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name`,
      )
      .all() as Array<{ name: string }>;
    const names = tables.map((t) => t.name);
    assert.ok(names.includes('sessions'), 'sessions table');
    assert.ok(names.includes('messages'), 'messages table');
    assert.ok(names.includes('processed_keys'), 'processed_keys table');
    assert.ok(names.includes('approvals'), 'approvals table');
    assert.ok(names.includes('audit_entries'), 'audit_entries table');
    assert.ok(names.includes('cron_jobs'), 'cron_jobs table');
    assert.ok(names.includes('device_tokens'), 'device_tokens table');
  });

  // ── Session CRUD ────────────────────────────────────────────

  it('inserts and retrieves a session', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-1', now, now);
    const row = db.getSession('sess-1');
    assert.ok(row);
    assert.equal(row.id, 'sess-1');
    assert.equal(row.created_at, now);
    assert.equal(row.last_activity, now);
  });

  it('returns undefined for missing session', () => {
    assert.equal(db.getSession('nonexistent'), undefined);
  });

  it('updates session activity', () => {
    const t1 = '2026-01-01T00:00:00.000Z';
    const t2 = '2026-01-01T01:00:00.000Z';
    db.insertSession('sess-2', t1, t1);
    db.updateSessionActivity('sess-2', t2);
    const row = db.getSession('sess-2');
    assert.equal(row?.last_activity, t2);
  });

  it('lists all sessions', () => {
    const now = new Date().toISOString();
    db.insertSession('s1', now, now);
    db.insertSession('s2', now, now);
    assert.equal(db.getAllSessions().length, 2);
  });

  it('gets active sessions since timestamp', () => {
    db.insertSession('old', '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z');
    db.insertSession('new', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
    const active = db.getActiveSessions('2025-12-01T00:00:00Z');
    assert.equal(active.length, 1);
    assert.equal(active[0].id, 'new');
  });

  it('cascades deletes from sessions to messages and keys', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-3', now, now);
    db.insertMessage('msg-1', 'sess-3', 'operator', '{}', now);
    db.insertProcessedKey('sess-3', 'key-1');
    db.deleteSession('sess-3');
    assert.equal(db.getRecentMessages('sess-3').length, 0);
    assert.equal(db.hasProcessedKey('sess-3', 'key-1'), false);
  });

  // ── Message persistence ─────────────────────────────────────

  it('stores and retrieves messages in order', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-4', now, now);
    db.insertMessage(
      'm1',
      'sess-4',
      'operator',
      '{"text":"hi"}',
      '2026-01-01T00:00:00Z',
    );
    db.insertMessage(
      'm2',
      'sess-4',
      'agent',
      '{"text":"hello"}',
      '2026-01-01T00:01:00Z',
    );
    const msgs = db.getRecentMessages('sess-4');
    assert.equal(msgs.length, 2);
    assert.equal(msgs[0].id, 'm1');
    assert.equal(msgs[1].id, 'm2');
  });

  it('respects limit on getRecentMessages', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-5', now, now);
    for (let i = 0; i < 10; i++) {
      db.insertMessage(
        `m${i}`,
        'sess-5',
        'agent',
        '{}',
        `2026-01-01T00:${String(i).padStart(2, '0')}:00Z`,
      );
    }
    const msgs = db.getRecentMessages('sess-5', 3);
    assert.equal(msgs.length, 3);
  });

  it('counts messages', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-count', now, now);
    db.insertMessage('mc1', 'sess-count', 'agent', '{}', now);
    db.insertMessage('mc2', 'sess-count', 'agent', '{}', now);
    assert.equal(db.getMessageCount('sess-count'), 2);
  });

  // ── Processed keys ──────────────────────────────────────────

  it('tracks idempotency keys', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-6', now, now);
    assert.equal(db.hasProcessedKey('sess-6', 'k1'), false);
    db.insertProcessedKey('sess-6', 'k1');
    assert.equal(db.hasProcessedKey('sess-6', 'k1'), true);
  });

  it('INSERT OR IGNORE does not throw on duplicate key', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-dup', now, now);
    db.insertProcessedKey('sess-dup', 'k1');
    db.insertProcessedKey('sess-dup', 'k1'); // should not throw
    assert.equal(db.getProcessedKeys('sess-dup').length, 1);
  });

  // ── Approvals ───────────────────────────────────────────────

  it('persists and resolves approvals', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-7', now, now);
    db.insertApproval(
      'ap-1',
      'sess-7',
      'task-1',
      'pay',
      'Pay $100',
      '{"amount":100}',
      now,
    );
    const pending = db.getPendingApprovals();
    assert.equal(pending.length, 1);
    assert.equal(pending[0].id, 'ap-1');
    assert.equal(pending[0].action, 'pay');

    db.resolveApproval('ap-1', 'approved');
    assert.equal(db.getPendingApprovals().length, 0);

    const resolved = db.getApproval('ap-1');
    assert.equal(resolved?.status, 'approved');
    assert.ok(resolved?.resolved_at);
  });

  it('cascades approval deletes with session', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-ap-del', now, now);
    db.insertApproval(
      'ap-del',
      'sess-ap-del',
      'task-x',
      'send',
      'Send email',
      '{}',
      now,
    );
    db.deleteSession('sess-ap-del');
    assert.equal(db.getApproval('ap-del'), undefined);
  });

  it('gets resolved approvals by session', () => {
    const now = new Date().toISOString();
    db.insertSession('s-res', now, now);
    db.insertApproval('ap-r1', 's-res', 't1', 'pay', 'Pay', '{}', now);
    db.insertApproval('ap-r2', 's-res', 't2', 'send', 'Send', '{}', now);
    db.resolveApproval('ap-r1', 'approved');
    const resolved = db.getResolvedApprovals('s-res');
    assert.equal(resolved.length, 1);
    assert.equal(resolved[0].id, 'ap-r1');
  });

  // ── Audit entries ───────────────────────────────────────────

  it('persists audit entries and computes summary', () => {
    const now = new Date().toISOString();
    db.insertAuditEntry('a1', 'task-1', 'search', 'auto_allowed', now, '{}');
    db.insertAuditEntry('a2', 'task-1', 'pay', 'approved', now, '{}');
    db.insertAuditEntry('a3', 'task-2', 'delete', 'denied', now, '{}');
    const summary = db.getAuditSummary();
    assert.equal(summary.total, 3);
    assert.equal(summary.approved, 1);
    assert.equal(summary.denied, 1);
    assert.equal(summary.autoAllowed, 1);
  });

  it('filters audit by task', () => {
    const now = new Date().toISOString();
    db.insertAuditEntry('a4', 'task-a', 'pay', 'approved', now, '{}');
    db.insertAuditEntry('a5', 'task-b', 'send', 'denied', now, '{}');
    const log = db.getAuditLog('task-a');
    assert.equal(log.length, 1);
    assert.equal(log[0].id, 'a4');
  });

  it('filters audit by action and decision', () => {
    const now = new Date().toISOString();
    db.insertAuditEntry('a6', 't1', 'pay', 'approved', now, '{}');
    db.insertAuditEntry('a7', 't2', 'pay', 'denied', now, '{}');
    db.insertAuditEntry('a8', 't3', 'send', 'approved', now, '{}');
    assert.equal(db.getAuditByAction('pay').length, 2);
    assert.equal(db.getAuditByDecision('approved').length, 2);
  });

  it('clears audit log', () => {
    const now = new Date().toISOString();
    db.insertAuditEntry('a9', 't1', 'pay', 'approved', now, '{}');
    db.clearAuditLog();
    assert.equal(db.getAuditLog().length, 0);
  });

  // ── Session pruning ─────────────────────────────────────────

  it('prunes old sessions', () => {
    db.insertSession('old', '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z');
    db.insertSession('new', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
    const pruned = db.pruneSessions('2025-12-01T00:00:00Z');
    assert.equal(pruned, 1);
    assert.equal(db.getSession('old'), undefined);
    assert.ok(db.getSession('new'));
  });

  // ── Cron jobs ───────────────────────────────────────────────

  it('inserts and retrieves cron jobs', () => {
    const now = new Date().toISOString();
    db.insertCronJob(
      'cron-1',
      'user-1',
      '0 9 * * *',
      'flight-search',
      'Search for flights',
      '{"from":"SFO"}',
      now,
    );
    const jobs = db.getEnabledCronJobs();
    assert.equal(jobs.length, 1);
    assert.equal(jobs[0].skill_name, 'flight-search');
  });

  it('disables cron job', () => {
    const now = new Date().toISOString();
    db.insertCronJob(
      'cron-2',
      'user-1',
      '0 9 * * *',
      'price-monitor',
      'Check prices',
      '{}',
      now,
    );
    db.disableCronJob('cron-2');
    assert.equal(db.getEnabledCronJobs().length, 0);
  });

  it('updates cron job run times', () => {
    const now = new Date().toISOString();
    const next = '2026-01-02T09:00:00Z';
    db.insertCronJob(
      'cron-3',
      'user-1',
      '0 9 * * *',
      'flight-search',
      'Search',
      '{}',
      now,
    );
    db.updateCronJobRun('cron-3', now, next);
    const jobs = db.getEnabledCronJobs();
    assert.equal(jobs[0].last_run, now);
    assert.equal(jobs[0].next_run, next);
  });
});

// ── SessionManager + Persistence integration ──────────────────────

describe('SessionManager + Persistence', () => {
  it('survives a simulated restart', () => {
    const tmpPath = `/tmp/clawbot-test-${Date.now()}.db`;

    // Phase 1: Create session with history and keys
    const dbA = new GatewayDB(tmpPath);
    const smA = new SessionManager(dbA);

    const session = smA.createSession();
    smA.addHistory(session.id, {
      id: 'msg-1',
      sessionId: session.id,
      sender: 'operator',
      message: { type: 'req', method: 'chat.send', payload: { text: 'hello' } },
      timestamp: new Date().toISOString(),
    });
    smA.addHistory(session.id, {
      id: 'msg-2',
      sessionId: session.id,
      sender: 'agent',
      message: {
        type: 'event',
        event: 'agent/stream:assistant',
        payload: { delta: 'Hi!' },
      },
      timestamp: new Date().toISOString(),
    });
    smA.markKeyProcessed(session.id, 'idem-key-1');

    smA.destroy();
    dbA.close();

    // Phase 2: New SessionManager from same DB file
    const dbB = new GatewayDB(tmpPath);
    const smB = new SessionManager(dbB);

    const recovered = smB.getSession(session.id);
    assert.ok(recovered, 'session should be recovered');
    assert.equal(recovered!.id, session.id);
    assert.equal(recovered!.history.length, 2);
    assert.equal(recovered!.history[0].id, 'msg-1');
    assert.equal(recovered!.history[1].id, 'msg-2');
    assert.equal(recovered!.processedKeys.has('idem-key-1'), true);
    assert.equal(recovered!.clients.size, 0, 'no live clients on startup');

    smB.destroy();
    dbB.close();

    try {
      unlinkSync(tmpPath);
    } catch {
      /* ignore */
    }
  });

  it('creates session in both memory and DB', () => {
    const db = new GatewayDB(':memory:');
    const sm = new SessionManager(db);

    const session = sm.createSession();
    const dbRow = db.getSession(session.id);

    assert.ok(dbRow, 'session should exist in DB');
    assert.equal(dbRow.id, session.id);

    sm.destroy();
    db.close();
  });

  it('persists messages through addHistory', () => {
    const db = new GatewayDB(':memory:');
    const sm = new SessionManager(db);

    const session = sm.createSession();
    sm.addHistory(session.id, {
      id: 'msg-persist',
      sessionId: session.id,
      sender: 'operator',
      message: { type: 'req', method: 'chat.send', payload: { text: 'test' } },
      timestamp: new Date().toISOString(),
    });

    const dbMsgs = db.getRecentMessages(session.id);
    assert.equal(dbMsgs.length, 1);
    assert.equal(dbMsgs[0].id, 'msg-persist');

    const content = JSON.parse(dbMsgs[0].content);
    assert.equal(content.payload.text, 'test');

    sm.destroy();
    db.close();
  });

  it('persists processed keys', () => {
    const db = new GatewayDB(':memory:');
    const sm = new SessionManager(db);

    const session = sm.createSession();
    sm.markKeyProcessed(session.id, 'key-persist');

    assert.equal(db.hasProcessedKey(session.id, 'key-persist'), true);
    assert.equal(db.hasProcessedKey(session.id, 'key-missing'), false);

    sm.destroy();
    db.close();
  });

  it('rehydrates on cache miss via getSession', () => {
    const tmpPath = `/tmp/clawbot-miss-${Date.now()}.db`;

    // Create session and force it into DB only
    const db1 = new GatewayDB(tmpPath);
    const now = new Date().toISOString();
    db1.insertSession('direct-insert', now, now);
    db1.insertMessage(
      'm-direct',
      'direct-insert',
      'system',
      '{"info":"boot"}',
      now,
    );
    db1.close();

    // New manager — session not in 24h window so not bulk-rehydrated
    // but getSession should fetch it on demand
    const db2 = new GatewayDB(tmpPath);
    const sm = new SessionManager(db2);

    const session = sm.getSession('direct-insert');
    assert.ok(session, 'should rehydrate from DB on cache miss');
    assert.equal(session!.history.length, 1);
    assert.equal(session!.history[0].id, 'm-direct');

    sm.destroy();
    db2.close();

    try {
      unlinkSync(tmpPath);
    } catch {
      /* ignore */
    }
  });
});

// ── Approval persistence integration ──────────────────────────────

describe('Approval persistence', () => {
  it('recovers pending approvals from DB', () => {
    const tmpPath = `/tmp/clawbot-approvals-${Date.now()}.db`;
    const now = new Date().toISOString();

    // Insert approval directly into DB (simulating pre-crash state)
    const db = new GatewayDB(tmpPath);
    db.insertSession('sess-r', now, now);
    db.insertApproval('ap-r1', 'sess-r', 'task-r', 'pay', 'Pay $50', '{}', now);
    db.close();

    // Reopen — pending approval should be recoverable
    const db2 = new GatewayDB(tmpPath);
    const pending = db2.getPendingApprovals();
    assert.equal(pending.length, 1);
    assert.equal(pending[0].id, 'ap-r1');
    assert.equal(pending[0].task_id, 'task-r');
    assert.equal(pending[0].action, 'pay');

    db2.close();
    try {
      unlinkSync(tmpPath);
    } catch {
      /* ignore */
    }
  });

  it('resolves approval and removes from pending', () => {
    const db = new GatewayDB(':memory:');
    const now = new Date().toISOString();

    db.insertSession('sess-ap', now, now);
    db.insertApproval(
      'ap-test',
      'sess-ap',
      'task-ap',
      'send',
      'Send email',
      '{}',
      now,
    );
    assert.equal(db.getPendingApprovals().length, 1);

    db.resolveApproval('ap-test', 'approved', 'user-123');
    assert.equal(db.getPendingApprovals().length, 0);

    const row = db.getApproval('ap-test');
    assert.equal(row?.status, 'approved');
    assert.equal(row?.resolved_by, 'user-123');
    assert.ok(row?.resolved_at);

    db.close();
  });
});
