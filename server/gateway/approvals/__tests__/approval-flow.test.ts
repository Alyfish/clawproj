import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createApprovalSystem, type ApprovalSystem } from '../index.js';

interface EmittedEvent {
  sessionId: string;
  event: string;
  payload: Record<string, unknown>;
}

describe('Approval System Integration', () => {
  let system: ApprovalSystem;
  let emitted: EmittedEvent[];

  function gatewayEmit(
    sessionId: string,
    event: string,
    payload: Record<string, unknown>,
  ): void {
    emitted.push({ sessionId, event, payload });
  }

  beforeEach(() => {
    emitted = [];
    system = createApprovalSystem(gatewayEmit, 600_000);
  });

  afterEach(() => {
    system.approvalManager.destroy();
  });

  it('auto-allows "search" without emitting approval/requested', async () => {
    const result = await system.approvalGate({
      taskId: 'task-1',
      action: 'search',
      description: 'Search for flights',
      context: {},
      sessionId: 'sess-1',
    });

    assert.equal(result, true);

    const reqEvents = emitted.filter((e) => e.event === 'approval/requested');
    assert.equal(reqEvents.length, 0, 'should not emit approval/requested');

    const log = system.auditLog.getLog('task-1');
    assert.equal(log.length, 1);
    assert.equal(log[0].decision, 'auto_allowed');
    assert.equal(log[0].action, 'search');
  });

  it('blocks on "pay", resolves true on approve', async () => {
    const gatePromise = system.approvalGate({
      taskId: 'task-2',
      action: 'pay',
      description: 'Pay $100',
      context: { amount: 100 },
      sessionId: 'sess-2',
    });

    // approval/requested should have been emitted synchronously
    const reqEvents = emitted.filter((e) => e.event === 'approval/requested');
    assert.equal(reqEvents.length, 1);
    const approvalId = reqEvents[0].payload.id as string;
    assert.ok(approvalId, 'approval ID should be present');

    // Resolve the approval
    system.approvalManager.resolve(approvalId, 'approved');
    const result = await gatePromise;

    assert.equal(result, true);

    const log = system.auditLog.getLog('task-2');
    assert.equal(log.length, 1);
    assert.equal(log[0].decision, 'approved');
  });

  it('blocks on "delete", resolves false on deny', async () => {
    const gatePromise = system.approvalGate({
      taskId: 'task-3',
      action: 'delete',
      description: 'Delete account',
      context: {},
      sessionId: 'sess-3',
    });

    const reqEvents = emitted.filter((e) => e.event === 'approval/requested');
    assert.equal(reqEvents.length, 1);
    const approvalId = reqEvents[0].payload.id as string;

    system.approvalManager.resolve(approvalId, 'denied');
    const result = await gatePromise;

    assert.equal(result, false);

    const log = system.auditLog.getLog('task-3');
    assert.equal(log.length, 1);
    assert.equal(log[0].decision, 'denied');
  });

  it('auto-denies on timeout', async () => {
    // Create system with 100ms timeout
    system.approvalManager.destroy();
    system = createApprovalSystem(gatewayEmit, 100);

    const result = await system.approvalGate({
      taskId: 'task-4',
      action: 'pay',
      description: 'Pay $50',
      context: { amount: 50 },
      sessionId: 'sess-4',
    });

    assert.equal(result, false);

    const timeoutEvents = emitted.filter((e) => e.event === 'approval/timeout');
    assert.equal(timeoutEvents.length, 1);

    const log = system.auditLog.getLog('task-4');
    assert.equal(log.length, 1);
    assert.equal(log[0].decision, 'denied');
  });

  it('cancelForTask denies pending approvals', async () => {
    const gate1 = system.approvalGate({
      taskId: 'task-5',
      action: 'pay',
      description: 'Pay $10',
      context: {},
      sessionId: 'sess-5',
    });

    const gate2 = system.approvalGate({
      taskId: 'task-5',
      action: 'send',
      description: 'Send email',
      context: {},
      sessionId: 'sess-5',
    });

    // Both should be pending
    assert.equal(system.approvalManager.pendingCount(), 2);

    const cancelled = system.approvalManager.cancelForTask('task-5');
    assert.equal(cancelled, 2);

    const [r1, r2] = await Promise.all([gate1, gate2]);
    assert.equal(r1, false);
    assert.equal(r2, false);

    assert.equal(system.approvalManager.pendingCount(), 0);
  });

  it('audit log captures full history across actions', async () => {
    // 1. auto_allowed search
    await system.approvalGate({
      taskId: 'task-6',
      action: 'search',
      description: 'Search',
      context: {},
      sessionId: 'sess-6',
    });

    // 2. approved pay
    const gatePromise = system.approvalGate({
      taskId: 'task-6',
      action: 'pay',
      description: 'Pay $200',
      context: { amount: 200 },
      sessionId: 'sess-6',
    });

    const reqEvents = emitted.filter((e) => e.event === 'approval/requested');
    const approvalId = reqEvents[0].payload.id as string;
    system.approvalManager.resolve(approvalId, 'approved');
    await gatePromise;

    const log = system.auditLog.getLog('task-6');
    assert.equal(log.length, 2);
    assert.equal(log[0].decision, 'auto_allowed');
    assert.equal(log[0].action, 'search');
    assert.equal(log[1].decision, 'approved');
    assert.equal(log[1].action, 'pay');

    const summary = system.auditLog.summary();
    assert.equal(summary.autoAllowed, 1);
    assert.equal(summary.approved, 1);
    assert.equal(summary.total, 2);
  });
});
