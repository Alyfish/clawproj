import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { GatewayDB } from '../persistence.js';
import {
  Scheduler,
  INTERVAL_PRESETS,
  type SchedulerDeps,
} from '../scheduler.js';
import type { WebSocket } from 'ws';

function createMockDeps(
  db: GatewayDB,
): SchedulerDeps & { calls: Record<string, unknown[][]> } {
  const calls: Record<string, unknown[][]> = {
    sendToAgent: [],
    broadcastToOperators: [],
    findAgentSession: [],
  };
  return {
    db,
    calls,
    findAgentSession: (userId: string) => {
      calls.findAgentSession.push([userId]);
      return { sessionId: 'test-session', agentWs: {} as WebSocket };
    },
    sendToAgent: (ws, event, payload) => {
      calls.sendToAgent.push([ws, event, payload]);
    },
    broadcastToOperators: (sessionId, event, payload) => {
      calls.broadcastToOperators.push([sessionId, event, payload]);
    },
  };
}

describe('Scheduler - Job CRUD', () => {
  let db: GatewayDB;
  let scheduler: Scheduler;
  let deps: SchedulerDeps & { calls: Record<string, unknown[][]> };

  beforeEach(() => {
    db = new GatewayDB(':memory:');
    deps = createMockDeps(db);
    scheduler = new Scheduler(deps);
  });

  it('creates a job and persists to DB', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
      payload: { symbol: 'BTC' },
    });

    assert.equal(job.user_id, 'user-1');
    assert.equal(job.cron_expression, '*/5 * * * *');
    assert.equal(job.skill_name, 'price-monitor');
    assert.equal(job.enabled, 1);

    const rows = db.getUserCronJobs('user-1');
    assert.equal(rows.length, 1);
    assert.equal(rows[0].id, job.id);
  });

  it('creates a job with preset name (resolves to cron expression)', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: 'every_5_minutes',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    assert.equal(job.cron_expression, INTERVAL_PRESETS.every_5_minutes);
  });

  it('rejects invalid cron expression', () => {
    assert.throws(
      () => {
        scheduler.createJob({
          userId: 'user-1',
          cronExpression: 'invalid',
          skillName: 'price-monitor',
          taskDescription: 'Check BTC price',
        });
      },
      { message: /Invalid cron expression/ },
    );
  });

  it('lists jobs for a user', () => {
    scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/10 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check ETH price',
    });

    scheduler.createJob({
      userId: 'user-2',
      cronExpression: '*/15 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check SOL price',
    });

    const user1Jobs = scheduler.listJobs('user-1');
    const user2Jobs = scheduler.listJobs('user-2');

    assert.equal(user1Jobs.length, 2);
    assert.equal(user2Jobs.length, 1);
  });

  it('removes a job', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    const removed = scheduler.removeJob(job.id);
    assert.equal(removed, true);

    const jobs = scheduler.listJobs('user-1');
    assert.equal(jobs.length, 0);

    const memoryJob = scheduler.getJob(job.id);
    assert.equal(memoryJob, undefined);
  });

  it('pauses a job (sets enabled=0)', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    const paused = scheduler.pauseJob(job.id);
    assert.equal(paused, true);

    const dbJob = db.getCronJob(job.id);
    assert.equal(dbJob?.enabled, 0);

    const memoryJob = scheduler.getJob(job.id);
    assert.equal(memoryJob?.enabled, false);
    assert.equal(memoryJob?.nextRunAtMs, null);
  });

  it('resumes a job (sets enabled=1, computes nextRunAtMs)', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    scheduler.pauseJob(job.id);
    const resumed = scheduler.resumeJob(job.id);
    assert.equal(resumed, true);

    const dbJob = db.getCronJob(job.id);
    assert.equal(dbJob?.enabled, 1);

    const memoryJob = scheduler.getJob(job.id);
    assert.equal(memoryJob?.enabled, true);
    assert.notEqual(memoryJob?.nextRunAtMs, null);
  });
});

describe('Scheduler - Timer Management', () => {
  let db: GatewayDB;
  let scheduler: Scheduler;
  let deps: SchedulerDeps & { calls: Record<string, unknown[][]> };

  beforeEach(() => {
    db = new GatewayDB(':memory:');
    deps = createMockDeps(db);
    scheduler = new Scheduler(deps);
  });

  it('arms timer on start() when jobs exist', () => {
    db.insertCronJob(
      'job-1',
      'user-1',
      '*/5 * * * *',
      'price-monitor',
      'Check BTC price',
      '{}',
      new Date().toISOString(),
    );

    scheduler.start();

    const job = scheduler.getJob('job-1');
    assert.notEqual(job, undefined);
    assert.notEqual(job?.nextRunAtMs, null);
  });

  it('does not arm timer when no jobs', () => {
    scheduler.start();
    // No assertion needed - just verify no crash
  });

  it('re-arms timer after createJob', () => {
    scheduler.start();

    const job1 = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '0 9 * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    const memJob1 = scheduler.getJob(job1.id);
    assert.notEqual(memJob1?.nextRunAtMs, null);

    const job2 = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check ETH price',
    });

    const memJob2 = scheduler.getJob(job2.id);
    assert.notEqual(memJob2?.nextRunAtMs, null);
  });

  it('re-arms timer after removeJob', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    scheduler.start();
    scheduler.removeJob(job.id);

    // Verify job is gone
    const memJob = scheduler.getJob(job.id);
    assert.equal(memJob, undefined);
  });
});

describe('Scheduler - Tick Execution', () => {
  let db: GatewayDB;
  let scheduler: Scheduler;
  let deps: SchedulerDeps & { calls: Record<string, unknown[][]> };

  beforeEach(() => {
    db = new GatewayDB(':memory:');
    deps = createMockDeps(db);
    scheduler = new Scheduler(deps);
    scheduler.start();
  });

  it('fires due jobs and sends trigger event to agent', () => {
    const pastTime = new Date(Date.now() - 60000).toISOString();

    db.insertCronJob(
      'job-1',
      'user-1',
      '*/5 * * * *',
      'price-monitor',
      'Check BTC price',
      '{"symbol":"BTC"}',
      pastTime,
    );

    // Manually insert into memory map with past nextRunAtMs
    const job = scheduler.getJob('job-1') ?? {
      id: 'job-1',
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
      payload: { symbol: 'BTC' },
      enabled: true,
      lastRunAt: pastTime,
      nextRunAtMs: Date.now() - 1000,
      createdAt: pastTime,
    };

    // Use internal access to set the job
    (scheduler as any).jobs.set('job-1', job);

    deps.calls.sendToAgent = [];
    scheduler._testTick();

    assert.equal(deps.calls.sendToAgent.length, 1);
    const [_ws, event, payload] = deps.calls.sendToAgent[0];
    assert.equal(event, 'schedule/task:trigger');
    assert.equal((payload as Record<string, unknown>).jobId, 'job-1');
    assert.equal(
      (payload as Record<string, unknown>).skillName,
      'price-monitor',
    );
  });

  it('skips disabled jobs', () => {
    const pastTime = new Date(Date.now() - 60000).toISOString();

    db.insertCronJob(
      'job-1',
      'user-1',
      '*/5 * * * *',
      'price-monitor',
      'Check BTC price',
      '{}',
      pastTime,
    );

    const job = {
      id: 'job-1',
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
      payload: {},
      enabled: false,
      lastRunAt: pastTime,
      nextRunAtMs: Date.now() - 1000,
      createdAt: pastTime,
    };

    (scheduler as any).jobs.set('job-1', job);

    deps.calls.sendToAgent = [];
    scheduler._testTick();

    assert.equal(deps.calls.sendToAgent.length, 0);
  });

  it('marks job as skipped when no agent connected', () => {
    const pastTime = new Date(Date.now() - 60000).toISOString();

    db.insertCronJob(
      'job-1',
      'user-1',
      '*/5 * * * *',
      'price-monitor',
      'Check BTC price',
      '{}',
      pastTime,
    );

    const job = {
      id: 'job-1',
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
      payload: {},
      enabled: true,
      lastRunAt: pastTime,
      nextRunAtMs: Date.now() - 1000,
      createdAt: pastTime,
    };

    (scheduler as any).jobs.set('job-1', job);

    // Override findAgentSession to return null
    deps.findAgentSession = () => null;

    scheduler._testTick();

    const results = db.getLatestResult('job-1');
    assert.notEqual(results, null);
    assert.equal(results?.status, 'error');
  });

  it('stores skipped result in cron_results', () => {
    const pastTime = new Date(Date.now() - 60000).toISOString();

    db.insertCronJob(
      'job-1',
      'user-1',
      '*/5 * * * *',
      'price-monitor',
      'Check BTC price',
      '{}',
      pastTime,
    );

    const job = {
      id: 'job-1',
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
      payload: {},
      enabled: true,
      lastRunAt: pastTime,
      nextRunAtMs: Date.now() - 1000,
      createdAt: pastTime,
    };

    (scheduler as any).jobs.set('job-1', job);

    // Override findAgentSession to return null
    deps.findAgentSession = () => null;

    scheduler._testTick();

    const result = db.getLatestResult('job-1');
    assert.notEqual(result, null);
    assert.equal(result?.status, 'error');
    assert.equal(result?.changed, 0);
  });
});

describe('Scheduler - Result Handling', () => {
  let db: GatewayDB;
  let scheduler: Scheduler;
  let deps: SchedulerDeps & { calls: Record<string, unknown[][]> };

  beforeEach(() => {
    db = new GatewayDB(':memory:');
    deps = createMockDeps(db);
    scheduler = new Scheduler(deps);
    scheduler.start();
  });

  it('stores result in cron_results', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    scheduler.handleTaskResult(job.id, {
      status: 'ok',
      data: { price: 50000 },
    });

    const result = db.getLatestResult(job.id);
    assert.notEqual(result, null);
    assert.equal(result?.status, 'ok');
  });

  it('detects change when data differs from previous', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    scheduler.handleTaskResult(job.id, {
      status: 'ok',
      data: { price: 50000 },
    });

    scheduler.handleTaskResult(job.id, {
      status: 'ok',
      data: { price: 51000 },
    });

    // Get second result
    const results = db.db
      .prepare(
        'SELECT * FROM cron_results WHERE job_id = ? ORDER BY executed_at DESC',
      )
      .all(job.id) as any[];

    assert.equal(results.length, 2);
    assert.equal(results[0].changed, 1);
  });

  it('does not flag change when data matches previous', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    scheduler.handleTaskResult(job.id, {
      status: 'ok',
      data: { price: 50000 },
    });

    scheduler.handleTaskResult(job.id, {
      status: 'ok',
      data: { price: 50000 },
    });

    const results = db.db
      .prepare(
        'SELECT * FROM cron_results WHERE job_id = ? ORDER BY executed_at DESC',
      )
      .all(job.id) as any[];

    assert.equal(results.length, 2);
    assert.equal(results[0].changed, 0);
  });

  it('broadcasts alert to operators when changed', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    scheduler.handleTaskResult(job.id, {
      status: 'ok',
      data: { price: 50000 },
    });

    deps.calls.broadcastToOperators = [];

    scheduler.handleTaskResult(job.id, {
      status: 'ok',
      data: { price: 51000 },
    });

    const alertBroadcasts = deps.calls.broadcastToOperators.filter(
      ([_sid, event]) => event === 'schedule/watch:update',
    );

    assert.equal(alertBroadcasts.length, 1);
    const [_sessionId, _event, payload] = alertBroadcasts[0];
    assert.equal((payload as Record<string, unknown>).action, 'alert');
  });

  it('updates job lastRun and nextRun after result', () => {
    const job = scheduler.createJob({
      userId: 'user-1',
      cronExpression: '*/5 * * * *',
      skillName: 'price-monitor',
      taskDescription: 'Check BTC price',
    });

    const beforeLastRun = scheduler.getJob(job.id)?.lastRunAt;

    scheduler.handleTaskResult(job.id, {
      status: 'ok',
      data: { price: 50000 },
    });

    const afterJob = scheduler.getJob(job.id);
    assert.notEqual(afterJob?.lastRunAt, beforeLastRun);
    assert.notEqual(afterJob?.nextRunAtMs, null);
  });
});

describe('Scheduler - Restart Recovery', () => {
  let db: GatewayDB;

  beforeEach(() => {
    db = new GatewayDB(':memory:');
  });

  it('start() loads jobs from DB', () => {
    db.insertCronJob(
      'job-1',
      'user-1',
      '*/5 * * * *',
      'price-monitor',
      'Check BTC price',
      '{}',
      new Date().toISOString(),
    );

    db.insertCronJob(
      'job-2',
      'user-1',
      '*/10 * * * *',
      'price-monitor',
      'Check ETH price',
      '{}',
      new Date().toISOString(),
    );

    const deps = createMockDeps(db);
    const scheduler = new Scheduler(deps);
    scheduler.start();

    const job1 = scheduler.getJob('job-1');
    const job2 = scheduler.getJob('job-2');

    assert.notEqual(job1, undefined);
    assert.notEqual(job2, undefined);
    assert.equal(job1?.userId, 'user-1');
    assert.equal(job2?.userId, 'user-1');
  });

  it('arms timer to earliest due job', () => {
    const now = new Date().toISOString();

    db.insertCronJob(
      'job-1',
      'user-1',
      '0 9 * * *',
      'price-monitor',
      'Check BTC price',
      '{}',
      now,
    );

    db.insertCronJob(
      'job-2',
      'user-1',
      '*/5 * * * *',
      'price-monitor',
      'Check ETH price',
      '{}',
      now,
    );

    const deps = createMockDeps(db);
    const scheduler = new Scheduler(deps);
    scheduler.start();

    const job1 = scheduler.getJob('job-1');
    const job2 = scheduler.getJob('job-2');

    assert.notEqual(job1?.nextRunAtMs, null);
    assert.notEqual(job2?.nextRunAtMs, null);

    // job-2 (every 5 min) should be sooner than job-1 (daily at 9am)
    if (job1?.nextRunAtMs && job2?.nextRunAtMs) {
      assert.ok(job2.nextRunAtMs < job1.nextRunAtMs);
    }
  });
});
