import { PolicyEngine } from './policy-engine.js';
import { AuditLog } from './audit-log.js';
import { ApprovalManager } from './approval-manager.js';
import { TaskControl } from './task-control.js';
import type { ApprovalAction } from '../../../shared/types/index.js';

export type { GatewayEmitFn } from './approval-manager.js';
export { PolicyEngine, AuditLog, ApprovalManager, TaskControl };

export interface ApprovalGateParams {
  taskId: string;
  action: string;
  description: string;
  context: Record<string, unknown>;
  sessionId: string;
}

export interface ApprovalSystem {
  approvalGate: (params: ApprovalGateParams) => Promise<boolean>;
  policyEngine: PolicyEngine;
  approvalManager: ApprovalManager;
  auditLog: AuditLog;
  taskControl: TaskControl;
}

export function createApprovalSystem(
  gatewayEmit: (
    sessionId: string,
    event: string,
    payload: Record<string, unknown>,
  ) => void,
  timeoutMs?: number,
): ApprovalSystem {
  const policyEngine = new PolicyEngine();
  const auditLog = new AuditLog();
  const approvalManager = new ApprovalManager(gatewayEmit, timeoutMs);
  const taskControl = new TaskControl(approvalManager, gatewayEmit);

  async function approvalGate(params: ApprovalGateParams): Promise<boolean> {
    const { taskId, action, description, context, sessionId } = params;
    const check = policyEngine.checkPolicy(action, context);

    if (!check.requiresApproval) {
      auditLog.log({
        taskId,
        action: action as ApprovalAction,
        decision: 'auto_allowed',
        context,
      });
      return true;
    }

    const decision = await approvalManager.createApproval(
      taskId,
      action as ApprovalAction,
      description,
      context,
      sessionId,
    );

    auditLog.log({
      taskId,
      action: action as ApprovalAction,
      decision,
      context,
    });

    return decision === 'approved';
  }

  return {
    approvalGate,
    policyEngine,
    approvalManager,
    auditLog,
    taskControl,
  };
}
