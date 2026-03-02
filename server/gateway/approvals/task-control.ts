import type { ApprovalManager, GatewayEmitFn } from './approval-manager.js';

export class TaskControl {
  constructor(
    private approvalManager: ApprovalManager,
    private gatewayEmit: GatewayEmitFn,
  ) {}

  stopTask(taskId: string, sessionId: string): { cancelledApprovals: number } {
    const cancelledApprovals = this.approvalManager.cancelForTask(taskId);

    this.gatewayEmit(sessionId, 'agent/stream:lifecycle', {
      status: 'end',
      runId: taskId,
      reason: 'user_stopped',
    });

    this.gatewayEmit(sessionId, 'task/update', {
      taskId,
      status: 'stopped',
    });

    console.log(
      JSON.stringify({ event: 'task:stopped', taskId, cancelledApprovals }),
    );

    return { cancelledApprovals };
  }

  stopMonitoring(watchlistItemId: string, sessionId: string): void {
    this.gatewayEmit(sessionId, 'monitoring/stopped', { watchlistItemId });

    console.log(
      JSON.stringify({ event: 'monitoring:stopped', watchlistItemId }),
    );
  }
}
