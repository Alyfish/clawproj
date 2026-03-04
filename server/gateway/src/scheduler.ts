import { Cron } from 'croner';
import { v4 as uuidv4 } from 'uuid';
import type { GatewayDB, CronJobRow } from './persistence.js';
import type { WebSocket } from 'ws';

export const INTERVAL_PRESETS: Record<string, string> = {
  every_5_minutes: '*/5 * * * *',
  every_15_minutes: '*/15 * * * *',
  every_hour: '0 * * * *',
  every_6_hours: '0 */6 * * *',
  daily_morning: '0 9 * * *',
  daily_evening: '0 18 * * *',
  weekly: '0 9 * * 1',
};

export interface SchedulerDeps {
  db: GatewayDB;
  findAgentSession: (
    userId: string,
  ) => { sessionId: string; agentWs: WebSocket } | null;
  sendToAgent: (
    ws: WebSocket,
    event: string,
    payload: Record<string, unknown>,
  ) => void;
  broadcastToOperators: (
    sessionId: string,
    event: string,
    payload: Record<string, unknown>,
  ) => void;
  log?: (
    level: 'info' | 'warn' | 'error',
    event: string,
    data?: Record<string, unknown>,
  ) => void;
}

interface ScheduledJob {
  id: string;
  userId: string;
  cronExpression: string;
  skillName: string;
  taskDescription: string;
  checkInstructions: string;
  payload: Record<string, unknown>;
  enabled: boolean;
  lastRunAt: string | null;
  nextRunAtMs: number | null;
  createdAt: string;
}

export class Scheduler {
  private deps: SchedulerDeps;
  private jobs: Map<string, ScheduledJob> = new Map();
  private timer: NodeJS.Timeout | null = null;

  constructor(deps: SchedulerDeps) {
    this.deps = deps;
  }

  start(): void {
    const rows = this.deps.db.getEnabledCronJobs();
    this.deps.log?.('info', 'scheduler:start', { count: rows.length });

    for (const row of rows) {
      const nextRunAtMs = this.computeNextRunMs(row.cron_expression);
      const parsedPayload = JSON.parse(row.payload);
      const job: ScheduledJob = {
        id: row.id,
        userId: row.user_id,
        cronExpression: row.cron_expression,
        skillName: row.skill_name,
        taskDescription: row.task_description,
        checkInstructions: (parsedPayload.checkInstructions as string) ?? '',
        payload: parsedPayload,
        enabled: row.enabled === 1,
        lastRunAt: row.last_run,
        nextRunAtMs,
        createdAt: row.created_at,
      };
      this.jobs.set(job.id, job);
    }

    this.armTimer();
  }

  stop(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  destroy(): void {
    this.stop();
    this.jobs.clear();
  }

  createJob(params: {
    userId: string;
    cronExpression: string;
    skillName: string;
    taskDescription: string;
    checkInstructions?: string;
    payload?: Record<string, unknown>;
  }): CronJobRow {
    // Resolve preset name if expression matches a preset key
    let expression = params.cronExpression;
    if (expression in INTERVAL_PRESETS) {
      expression = INTERVAL_PRESETS[expression];
    }

    // Validate cron expression
    if (!Scheduler.isValidExpression(expression)) {
      throw new Error(`Invalid cron expression: ${expression}`);
    }

    const id = uuidv4();
    const now = new Date().toISOString();
    const checkInstructions = params.checkInstructions ?? '';
    const payload = {
      ...(params.payload ?? {}),
      checkInstructions,
    };

    this.deps.db.insertCronJob(
      id,
      params.userId,
      expression,
      params.skillName,
      params.taskDescription,
      JSON.stringify(payload),
      now,
    );

    const nextRunAtMs = this.computeNextRunMs(expression);
    const job: ScheduledJob = {
      id,
      userId: params.userId,
      cronExpression: expression,
      skillName: params.skillName,
      taskDescription: params.taskDescription,
      checkInstructions,
      payload,
      enabled: true,
      lastRunAt: null,
      nextRunAtMs,
      createdAt: now,
    };

    this.jobs.set(id, job);
    this.armTimer();
    this.broadcastWatchUpdate(job, 'created');

    const row = this.deps.db.getCronJob(id);
    if (!row) {
      throw new Error(`Failed to retrieve created job ${id}`);
    }
    return row;
  }

  listJobs(userId: string): CronJobRow[] {
    return this.deps.db.getUserCronJobs(userId);
  }

  removeJob(jobId: string): boolean {
    const job = this.jobs.get(jobId);
    if (!job) {
      return false;
    }

    this.deps.db.deleteCronJob(jobId);
    this.jobs.delete(jobId);
    this.armTimer();
    this.broadcastWatchUpdate(job, 'removed');

    return true;
  }

  pauseJob(jobId: string): boolean {
    const job = this.jobs.get(jobId);
    if (!job) {
      return false;
    }

    this.deps.db.disableCronJob(jobId);
    job.enabled = false;
    job.nextRunAtMs = null;
    this.armTimer();
    this.broadcastWatchUpdate(job, 'paused');

    return true;
  }

  resumeJob(jobId: string): boolean {
    const job = this.jobs.get(jobId);
    if (!job) {
      return false;
    }

    this.deps.db.enableCronJob(jobId);
    job.enabled = true;
    job.nextRunAtMs = this.computeNextRunMs(job.cronExpression);
    this.armTimer();
    this.broadcastWatchUpdate(job, 'resumed');

    return true;
  }

  handleTaskResult(
    jobId: string,
    result: {
      status: 'ok' | 'error';
      data: Record<string, unknown>;
      summary?: string;
    },
  ): void {
    const job = this.jobs.get(jobId);
    if (!job) {
      this.deps.log?.('warn', 'scheduler:handleTaskResult:jobNotFound', {
        jobId,
      });
      return;
    }

    const previousResult = this.deps.db.getLatestResult(jobId);
    let changed = false;
    let previousData: Record<string, unknown> | null = null;

    if (result.status === 'ok' && previousResult?.result_data) {
      try {
        previousData = JSON.parse(previousResult.result_data);
        const currentData = result.data;
        changed = JSON.stringify(currentData) !== JSON.stringify(previousData);
      } catch {
        // If parsing fails, treat as changed
        changed = true;
      }
    } else if (result.status === 'ok') {
      // First run, mark as changed
      changed = true;
    }

    const now = new Date().toISOString();
    this.deps.db.insertCronResult(
      uuidv4(),
      jobId,
      result.status,
      JSON.stringify(result.data),
      previousData ? JSON.stringify(previousData) : null,
      changed,
      now,
    );

    if (changed && result.status === 'ok') {
      const alert = {
        type: job.skillName,
        data: result.data,
        timestamp: now,
      };
      this.broadcastWatchUpdate(job, 'alert', alert);
    }

    job.lastRunAt = now;
    job.nextRunAtMs = this.computeNextRunMs(job.cronExpression);

    const nextRunStr = job.nextRunAtMs
      ? new Date(job.nextRunAtMs).toISOString()
      : now;
    this.deps.db.updateCronJobRun(jobId, now, nextRunStr);
    this.armTimer();
  }

  getJob(jobId: string): ScheduledJob | undefined {
    return this.jobs.get(jobId);
  }

  // Exposed for testing
  _testTick(): void {
    this.tick();
  }

  private armTimer(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }

    let earliest: ScheduledJob | null = null;
    let earliestMs = Infinity;

    for (const job of this.jobs.values()) {
      if (
        job.enabled &&
        job.nextRunAtMs !== null &&
        job.nextRunAtMs < earliestMs
      ) {
        earliest = job;
        earliestMs = job.nextRunAtMs;
      }
    }

    if (!earliest) {
      this.deps.log?.('info', 'scheduler:armTimer:noJobs');
      return;
    }

    const delay = Math.max(1000, earliestMs - Date.now());
    this.timer = setTimeout(() => this.tick(), delay);
    if (this.timer.unref) {
      this.timer.unref();
    }

    this.deps.log?.('info', 'scheduler:armTimer', {
      jobId: earliest.id,
      delayMs: delay,
    });
  }

  private tick(): void {
    const now = Date.now();
    const dueJobs: ScheduledJob[] = [];

    for (const job of this.jobs.values()) {
      if (job.enabled && job.nextRunAtMs !== null && job.nextRunAtMs <= now) {
        dueJobs.push(job);
      }
    }

    this.deps.log?.('info', 'scheduler:tick', { count: dueJobs.length });

    for (const job of dueJobs) {
      const agentSession = this.deps.findAgentSession(job.userId);

      if (!agentSession) {
        this.deps.log?.('warn', 'scheduler:tick:noAgent', {
          jobId: job.id,
          userId: job.userId,
        });

        const nowStr = new Date().toISOString();
        this.deps.db.insertCronResult(
          uuidv4(),
          job.id,
          'error',
          JSON.stringify({}),
          null,
          false,
          nowStr,
        );

        job.nextRunAtMs = this.computeNextRunMs(job.cronExpression);
        const nextRunStr = job.nextRunAtMs
          ? new Date(job.nextRunAtMs).toISOString()
          : nowStr;
        this.deps.db.updateCronJobRun(job.id, nowStr, nextRunStr);
        continue;
      }

      const previousResult = this.deps.db.getLatestResult(job.id);
      const payload: Record<string, unknown> = {
        jobId: job.id,
        taskDescription: job.taskDescription,
        skillName: job.skillName,
        checkInstructions: job.checkInstructions,
        payload: job.payload,
      };

      if (previousResult && previousResult.result_data) {
        payload.previousResult = {
          status: previousResult.status,
          data: JSON.parse(previousResult.result_data),
          executedAt: previousResult.executed_at,
        };
      }

      this.deps.sendToAgent(
        agentSession.agentWs,
        'schedule/task:trigger',
        payload,
      );
      this.deps.log?.('info', 'scheduler:tick:triggered', {
        jobId: job.id,
        userId: job.userId,
      });
    }

    this.armTimer();
  }

  private computeNextRunMs(cronExpression: string): number | null {
    try {
      const job = new Cron(cronExpression);
      const next = job.nextRun();
      return next ? next.getTime() : null;
    } catch (error) {
      this.deps.log?.('error', 'scheduler:computeNextRunMs:error', {
        cronExpression,
        error,
      });
      return null;
    }
  }

  private broadcastWatchUpdate(
    job: ScheduledJob,
    action: 'created' | 'removed' | 'paused' | 'resumed' | 'alert',
    alert?: Record<string, unknown>,
  ): void {
    const agentSession = this.deps.findAgentSession(job.userId);
    if (!agentSession) {
      return;
    }

    const nextRun = job.nextRunAtMs
      ? new Date(job.nextRunAtMs).toISOString()
      : null;

    const payload: Record<string, unknown> = {
      action,
      watch: {
        id: job.id,
        type: job.skillName,
        description: job.taskDescription,
        interval: job.cronExpression,
        lastChecked: job.lastRunAt,
        active: job.enabled,
        nextRun,
      },
    };

    if (alert) {
      payload.alert = alert;
    }

    this.deps.broadcastToOperators(
      agentSession.sessionId,
      'schedule/watch:update',
      payload,
    );
  }

  static isValidExpression(expr: string): boolean {
    // Resolve preset if needed
    let expression = expr;
    if (expression in INTERVAL_PRESETS) {
      expression = INTERVAL_PRESETS[expression];
    }

    try {
      new Cron(expression);
      return true;
    } catch {
      return false;
    }
  }
}
