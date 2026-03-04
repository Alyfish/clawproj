import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { GatewayDB } from '../persistence.js';

// ── Device tokens persistence tests ─────────────────────────────

describe('device_tokens', () => {
  let db: GatewayDB;

  beforeEach(() => {
    db = new GatewayDB(':memory:');
  });

  afterEach(() => {
    db.close();
  });

  it('creates device_tokens table', () => {
    const tables = db.db
      .prepare(
        `SELECT name FROM sqlite_master WHERE type='table' AND name = 'device_tokens'`,
      )
      .all() as Array<{ name: string }>;
    assert.equal(tables.length, 1);
  });

  it('registers and retrieves device token', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-push', now, now);
    db.registerDeviceToken('abc123token00', 'sess-push', 'ios');
    const tokens = db.getDeviceTokensForSession('sess-push');
    assert.equal(tokens.length, 1);
    assert.equal(tokens[0].token, 'abc123token00');
    assert.equal(tokens[0].platform, 'ios');
    assert.equal(tokens[0].session_id, 'sess-push');
  });

  it('upserts on re-registration with new session', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-a', now, now);
    db.insertSession('sess-b', now, now);
    db.registerDeviceToken('token-upsert0', 'sess-a', 'ios');
    db.registerDeviceToken('token-upsert0', 'sess-b', 'ios');
    assert.equal(db.getDeviceTokensForSession('sess-a').length, 0);
    assert.equal(db.getDeviceTokensForSession('sess-b').length, 1);
    assert.equal(
      db.getDeviceTokensForSession('sess-b')[0].token,
      'token-upsert0',
    );
  });

  it('unregisters device token', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-unreg', now, now);
    db.registerDeviceToken('token-delete0', 'sess-unreg', 'ios');
    db.unregisterDeviceToken('token-delete0');
    assert.equal(db.getDeviceTokensForSession('sess-unreg').length, 0);
  });

  it('cascades delete with session', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-cascade', now, now);
    db.registerDeviceToken('token-cascade', 'sess-cascade', 'ios');
    db.deleteSession('sess-cascade');
    const row = db.db
      .prepare(`SELECT * FROM device_tokens WHERE token = ?`)
      .get('token-cascade');
    assert.equal(row, undefined);
  });

  it('removes stale tokens', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-stale', now, now);
    db.registerDeviceToken('token-old000', 'sess-stale', 'ios');
    // Manually set last_used to old date
    db.db
      .prepare(`UPDATE device_tokens SET last_used = ? WHERE token = ?`)
      .run('2025-01-01T00:00:00Z', 'token-old000');
    const removed = db.removeStaleTokens('2025-12-01T00:00:00Z');
    assert.equal(removed, 1);
    assert.equal(db.getDeviceTokensForSession('sess-stale').length, 0);
  });

  it('handles multiple tokens per session', () => {
    const now = new Date().toISOString();
    db.insertSession('sess-multi', now, now);
    db.registerDeviceToken('token-ipad0', 'sess-multi', 'ios');
    db.registerDeviceToken('token-phone', 'sess-multi', 'ios');
    const tokens = db.getDeviceTokensForSession('sess-multi');
    assert.equal(tokens.length, 2);
    const tokenValues = tokens.map((t) => t.token).sort();
    assert.deepEqual(tokenValues, ['token-ipad0', 'token-phone']);
  });

  it('returns empty array for unknown session', () => {
    const tokens = db.getDeviceTokensForSession('nonexistent');
    assert.equal(tokens.length, 0);
  });
});
