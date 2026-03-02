import { v4 as uuidv4 } from 'uuid';
import type {
  ApprovalAction,
  ApprovalDecision,
  ApprovalRequest,
  ApprovalResponse,
} from '../../../shared/types/index.js';

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
  // TODO: Replace with persistent store
  private pending: Map<string, PendingApproval> = new Map();
  // TODO: Replace with persistent store
  private resolved: Map<
    string,
    { request: ApprovalRequest; response: ApprovalResponse }
  > = new Map();

  constructor(
    private gatewayEmit: GatewayEmitFn,
    private timeoutMs: number = 600_000,
  ) {}

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
