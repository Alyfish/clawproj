import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { PolicyEngine } from '../policy-engine.js';

describe('PolicyEngine', () => {
  let engine: PolicyEngine;

  beforeEach(() => {
    engine = new PolicyEngine();
  });

  // ALWAYS_ASK actions (5 tests)
  it('requires approval for "submit"', () => {
    const result = engine.checkPolicy('submit');
    assert.equal(result.requiresApproval, true);
    assert.ok(result.reason.includes('safety-critical'));
  });

  it('requires approval for "pay"', () => {
    const result = engine.checkPolicy('pay');
    assert.equal(result.requiresApproval, true);
    assert.ok(result.reason.includes('safety-critical'));
  });

  it('requires approval for "send"', () => {
    const result = engine.checkPolicy('send');
    assert.equal(result.requiresApproval, true);
    assert.ok(result.reason.includes('safety-critical'));
  });

  it('requires approval for "delete"', () => {
    const result = engine.checkPolicy('delete');
    assert.equal(result.requiresApproval, true);
    assert.ok(result.reason.includes('safety-critical'));
  });

  it('requires approval for "share_personal_info"', () => {
    const result = engine.checkPolicy('share_personal_info');
    assert.equal(result.requiresApproval, true);
    assert.ok(result.reason.includes('safety-critical'));
  });

  // "never" actions
  it('does not require approval for "search"', () => {
    const result = engine.checkPolicy('search');
    assert.equal(result.requiresApproval, false);
  });

  it('does not require approval for "read"', () => {
    const result = engine.checkPolicy('read');
    assert.equal(result.requiresApproval, false);
  });

  // configurable actions
  it('allows "monitor" when target is in allowlist', () => {
    const result = engine.checkPolicy('monitor', { target: 'portfolio' });
    assert.equal(result.requiresApproval, false);
    assert.ok(result.reason.includes('allowlist'));
  });

  it('requires approval for "monitor" when target is not in allowlist', () => {
    const result = engine.checkPolicy('monitor', { target: 'unknown_thing' });
    assert.equal(result.requiresApproval, true);
  });

  it('requires approval for "monitor" when no target provided', () => {
    const result = engine.checkPolicy('monitor');
    assert.equal(result.requiresApproval, true);
  });

  // unknown action
  it('requires approval for unknown actions (safe-by-default)', () => {
    const result = engine.checkPolicy('hack_nasa');
    assert.equal(result.requiresApproval, true);
    assert.ok(result.reason.includes('unknown'));
  });

  // reason presence
  it('always includes a reason string', () => {
    const actions = ['submit', 'search', 'monitor', 'totally_unknown'];
    for (const action of actions) {
      const result = engine.checkPolicy(action);
      assert.ok(
        typeof result.reason === 'string' && result.reason.length > 0,
        `missing reason for "${action}"`,
      );
    }
  });
});
