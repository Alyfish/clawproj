import { v4 as uuidv4 } from 'uuid';
import type {
  ApprovalAction,
  ApprovalDecision,
  ApprovalRequest,
  ApprovalResponse,
} from '../../../shared/types/index.js';
import type { GatewayDB } from '../src/persistence.js';

export type GatewayEmitFn = (
  sessionId: string,
  event: string,
  payload: Record<string, unknown>,
) => void;

interface PendingApproval {
  request: ApprovalRequest;
  sessionId: string;
  resolve: (decision: ApprovalDecision) => void;
  timeoutId: NodeJS.Timeout;
}

export class ApprovalManager {
  private pending: Map<string, PendingApproval> = new Map();
  private resolved: Map<
    string,
    { request: ApprovalRequest; response: ApprovalResponse }
  > = new Map();

  constructor(
    private gatewayEmit: GatewayEmitFn,
    private timeoutMs: number = 600_000,
    private db?: GatewayDB,
  ) {
    if (this.db) {
      this.rehydratePending();
    }
  }

  private rehydratePending(): void {
    if (!this.db) return;

    const rows = this.db.getPendingApprovals();
    const now = Date.now();
    let recovered = 0;
    let expired = 0;

    for (const row of rows) {
      const createdAtMs = new Date(row.created_at).getTime();
      const elapsed = now - createdAtMs;
      const remaining = this.timeoutMs - elapsed;

      // Already past timeout — mark as denied
      if (remaining <= 0) {
        this.db.resolveApproval(row.id, 'denied');
        expired++;
        continue;
      }

      const request: ApprovalRequest = {
        id: row.id,
        taskId: row.task_id,
        action: row.action as ApprovalAction,
        description: row.description,
        details: JSON.parse(row.details),
        createdAt: row.created_at,
      };

      // Create fresh Promise + timeout with remaining time
      let resolveCallback!: (decision: ApprovalDecision) => void;
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const _promise = new Promise<ApprovalDecision>((res) => {
        resolveCallback = res;
      });

      const timeoutId = setTimeout(() => {
        if (this.pending.has(row.id)) {
          this.pending.delete(row.id);
          this.resolved.set(row.id, {
            request,
            response: {
              id: row.id,
              decision: 'denied',
              decidedAt: new Date().toISOString(),
            },
          });
          this.db?.resolveApproval(row.id, 'denied');
          this.gatewayEmit(row.session_id, 'approval/timeout', {
            approvalId: row.id,
            taskId: row.task_id,
          });
          resolveCallback('denied');
        }
      }, remaining);

      this.pending.set(row.id, {
        request,
        sessionId: row.session_id,
        resolve: resolveCallback,
        timeoutId,
      });
      recovered++;
    }

    console.log(
      JSON.stringify({
        level: 'info',
        event: 'approvals:rehydrated',
        data: { recovered, expired },
        timestamp: new Date().toISOString(),
      }),
    );
  }

  createApproval(
    taskId: string,
    action: ApprovalAction,
    description: string,
    details: Record<string, unknown>,
    sessionId: string,
  ): Promise<ApprovalDecision> {
    const id = uuidv4();
    const createdAt = new Date().toISOString();
    const request: ApprovalRequest = {
      id,
      taskId,
      action,
      description,
      details,
      createdAt,
    };

    // Write-through to SQLite
    this.db?.insertApproval(
      id,
      sessionId,
      taskId,
      action,
      description,
      JSON.stringify(details),
      createdAt,
    );

    return new Promise<ApprovalDecision>((resolve) => {
      const timeoutId = setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          this.resolved.set(id, {
            request,
            response: {
              id,
              decision: 'denied',
              decidedAt: new Date().toISOString(),
            },
          });
          this.db?.resolveApproval(id, 'denied');
          this.gatewayEmit(sessionId, 'approval/timeout', {
            approvalId: id,
            taskId,
          });
          console.log(
            JSON.stringify({
              event: 'approval:timeout',
              approvalId: id,
              taskId,
            }),
          );
          resolve('denied');
        }
      }, this.timeoutMs);

      this.pending.set(id, { request, sessionId, resolve, timeoutId });
      this.gatewayEmit(sessionId, 'approval/requested', { ...request });
      console.log(
        JSON.stringify({
          event: 'approval:created',
          approvalId: id,
          taskId,
          action,
        }),
      );
    });
  }

  resolve(
    approvalId: string,
    decision: ApprovalDecision,
  ): ApprovalResponse | null {
    const entry = this.pending.get(approvalId);
    if (!entry) return null;

    clearTimeout(entry.timeoutId);
    this.pending.delete(approvalId);

    const response: ApprovalResponse = {
      id: approvalId,
      decision,
      decidedAt: new Date().toISOString(),
    };
    this.resolved.set(approvalId, { request: entry.request, response });

    // Write-through to SQLite
    this.db?.resolveApproval(approvalId, decision);

    entry.resolve(decision);

    this.gatewayEmit(entry.sessionId, 'approval/resolved', {
      approvalId,
      decision,
      taskId: entry.request.taskId,
    });
    console.log(
      JSON.stringify({
        event: 'approval:resolved',
        approvalId,
        decision,
        taskId: entry.request.taskId,
      }),
    );

    return response;
  }

  listPending(sessionId?: string): ApprovalRequest[] {
    const entries = [...this.pending.values()];
    if (sessionId) {
      return entries
        .filter((e) => e.sessionId === sessionId)
        .map((e) => e.request);
    }
    return entries.map((e) => e.request);
  }

  getPending(approvalId: string): ApprovalRequest | undefined {
    return this.pending.get(approvalId)?.request;
  }

  getResolved(
    approvalId: string,
  ): { request: ApprovalRequest; response: ApprovalResponse } | undefined {
    return this.resolved.get(approvalId);
  }

  cancelForTask(taskId: string): number {
    let count = 0;
    for (const [id, entry] of this.pending) {
      if (entry.request.taskId === taskId) {
        clearTimeout(entry.timeoutId);
        entry.resolve('denied');
        this.pending.delete(id);
        this.resolved.set(id, {
          request: entry.request,
          response: {
            id,
            decision: 'denied',
            decidedAt: new Date().toISOString(),
          },
        });
        // Write-through to SQLite
        this.db?.resolveApproval(id, 'cancelled');
        count++;
      }
    }
    return count;
  }

  pendingCount(): number {
    return this.pending.size;
  }

  destroy(): void {
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timeoutId);
    }
    this.pending.clear();
    this.resolved.clear();
  }
}
