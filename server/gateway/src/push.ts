import apn from '@parse/node-apn';
import { z } from 'zod';
import type { GatewayDB } from './persistence.js';

// ── Configuration ──────────────────────────────────────────────

const PushConfigSchema = z.object({
  keyPath: z.string().min(1),
  keyId: z.string().min(1),
  teamId: z.string().min(1),
  bundleId: z.string().min(1),
  production: z.boolean(),
});

export type PushConfig = z.infer<typeof PushConfigSchema>;

// ── Notification types ─────────────────────────────────────────

export type PushNotificationType =
  | 'APPROVAL_REQUEST'
  | 'TASK_COMPLETE'
  | 'PRICE_ALERT'
  | 'AGENT_MESSAGE';

// iOS category IDs — must match NotificationManager.swift constants
const CATEGORY_MAP: Record<PushNotificationType, string> = {
  APPROVAL_REQUEST: 'APPROVAL_NEEDED',
  TASK_COMPLETE: 'TASK_COMPLETED',
  PRICE_ALERT: 'PRICE_ALERT',
  AGENT_MESSAGE: '',
};

// ── Logging ────────────────────────────────────────────────────

function log(
  level: 'info' | 'warn' | 'error',
  event: string,
  data?: Record<string, unknown>,
): void {
  console.log(
    JSON.stringify({ level, event, data, timestamp: new Date().toISOString() }),
  );
}

// ── PushService ────────────────────────────────────────────────

export class PushService {
  private provider: apn.Provider;
  private bundleId: string;
  private db: GatewayDB;

  constructor(config: PushConfig, db: GatewayDB) {
    this.bundleId = config.bundleId;
    this.db = db;
    this.provider = new apn.Provider({
      token: {
        key: config.keyPath,
        keyId: config.keyId,
        teamId: config.teamId,
      },
      production: config.production,
    });
    log('info', 'push:initialized', { production: config.production });
  }

  // ── Public send methods ──────────────────────────────────────

  async sendApprovalRequest(
    sessionId: string,
    approval: {
      id: string;
      taskId: string;
      action: string;
      description: string;
    },
  ): Promise<void> {
    const tokens = this.getTokensForSession(sessionId);
    if (tokens.length === 0) return;

    const note = this.buildNotification('APPROVAL_REQUEST', {
      title: `Approval Required: ${approval.action}`,
      body: approval.description,
      collapseId: `approval-${approval.id}`,
      userInfo: {
        approvalId: approval.id,
        taskId: approval.taskId,
        action: approval.action,
        type: 'APPROVAL_REQUEST',
      },
      deepLink: `clawbot://approval/${approval.id}`,
    });

    await this.send(tokens, note, 'APPROVAL_REQUEST');
  }

  async sendTaskComplete(
    sessionId: string,
    task: { taskId: string; summary?: string },
  ): Promise<void> {
    const tokens = this.getTokensForSession(sessionId);
    if (tokens.length === 0) return;

    const note = this.buildNotification('TASK_COMPLETE', {
      title: 'Task Completed',
      body: task.summary ?? 'Your task has finished.',
      collapseId: `task-${task.taskId}`,
      userInfo: {
        taskId: task.taskId,
        type: 'TASK_COMPLETE',
      },
      deepLink: `clawbot://task/${task.taskId}`,
    });

    await this.send(tokens, note, 'TASK_COMPLETE');
  }

  async sendPriceAlert(
    sessionId: string,
    alert: {
      taskId: string;
      title: string;
      body: string;
    },
  ): Promise<void> {
    const tokens = this.getTokensForSession(sessionId);
    if (tokens.length === 0) return;

    const note = this.buildNotification('PRICE_ALERT', {
      title: alert.title,
      body: alert.body,
      collapseId: `price-${alert.taskId}`,
      userInfo: {
        taskId: alert.taskId,
        type: 'PRICE_ALERT',
      },
      deepLink: `clawbot://task/${alert.taskId}`,
    });

    await this.send(tokens, note, 'PRICE_ALERT');
  }

  async sendAgentMessage(
    sessionId: string,
    message: { text: string },
  ): Promise<void> {
    const tokens = this.getTokensForSession(sessionId);
    if (tokens.length === 0) return;

    const truncated =
      message.text.length > 200
        ? message.text.slice(0, 197) + '...'
        : message.text;

    const note = this.buildNotification('AGENT_MESSAGE', {
      title: 'ClawBot',
      body: truncated,
      userInfo: { type: 'AGENT_MESSAGE' },
    });

    await this.send(tokens, note, 'AGENT_MESSAGE');
  }

  // ── Test push (for /api/test-push endpoint) ──────────────────

  async sendTestPush(
    tokens: string[],
    type: PushNotificationType,
  ): Promise<{ sent: number; failed: number }> {
    const note = this.buildNotification(type, {
      title: `Test: ${type}`,
      body: `This is a test ${type} notification from ClawBot.`,
      userInfo: { type, test: true },
    });
    return this.send(tokens, note, type);
  }

  // ── Lifecycle ────────────────────────────────────────────────

  shutdown(): void {
    this.provider.shutdown();
    log('info', 'push:shutdown');
  }

  // ── Private helpers ──────────────────────────────────────────

  private getTokensForSession(sessionId: string): string[] {
    const rows = this.db.getDeviceTokensForSession(sessionId);
    return rows.map((r) => r.token);
  }

  private buildNotification(
    type: PushNotificationType,
    params: {
      title: string;
      body: string;
      collapseId?: string;
      userInfo?: Record<string, unknown>;
      deepLink?: string;
    },
  ): apn.Notification {
    const note = new apn.Notification();

    note.expiry = Math.floor(Date.now() / 1000) + 3600; // 1 hour
    note.sound = 'default';
    note.alert = { title: params.title, body: params.body };
    note.topic = this.bundleId;
    note.threadId = type;
    note.mutableContent = true;

    const category = CATEGORY_MAP[type];
    if (category) {
      note.aps.category = category;
    }

    if (params.collapseId) {
      note.collapseId = params.collapseId;
    }

    note.payload = {
      ...params.userInfo,
    };

    if (params.deepLink) {
      note.payload.deepLink = params.deepLink;
    }

    return note;
  }

  private async send(
    tokens: string[],
    note: apn.Notification,
    type: string,
  ): Promise<{ sent: number; failed: number }> {
    try {
      const result = await this.provider.send(note, tokens);

      // Clean up invalid tokens
      for (const failure of result.failed) {
        if (
          failure.status === 410 ||
          failure.response?.reason === 'Unregistered' ||
          failure.response?.reason === 'BadDeviceToken'
        ) {
          log('info', 'push:token_removed', {
            device: failure.device,
            reason: failure.response?.reason ?? failure.status,
          });
          this.db.unregisterDeviceToken(failure.device);
        }
      }

      const sent = result.sent.length;
      const failed = result.failed.length;

      log('info', 'push:sent', { type, sent, failed });
      return { sent, failed };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Push send failed';
      log('error', 'push:error', { type, error: message });
      return { sent: 0, failed: tokens.length };
    }
  }
}

// ── Factory ────────────────────────────────────────────────────

export function createPushService(db: GatewayDB): PushService | null {
  const keyPath = process.env.APNS_KEY_PATH;
  const keyId = process.env.APNS_KEY_ID;
  const teamId = process.env.APNS_TEAM_ID;
  const bundleId = process.env.APNS_BUNDLE_ID;
  const production = process.env.APNS_PRODUCTION === 'true';

  if (!keyPath || !keyId || !teamId || !bundleId) {
    log('warn', 'push:disabled', {
      reason: 'Missing APNS_* environment variables',
      missing: [
        !keyPath && 'APNS_KEY_PATH',
        !keyId && 'APNS_KEY_ID',
        !teamId && 'APNS_TEAM_ID',
        !bundleId && 'APNS_BUNDLE_ID',
      ].filter(Boolean),
    });
    return null;
  }

  const config = PushConfigSchema.parse({
    keyPath,
    keyId,
    teamId,
    bundleId,
    production,
  });

  return new PushService(config, db);
}
