/** Actions that always require user approval before execution */
export type ApprovalAction =
  | 'submit'
  | 'pay'
  | 'send'
  | 'delete'
  | 'share_personal_info';

export type ApprovalDecision = 'approved' | 'denied';

export interface ApprovalRequest {
  id: string;
  taskId: string;
  action: ApprovalAction;
  description: string;
  /** Structured context relevant to the action (e.g. form fields, payment amount) */
  details: Record<string, unknown>;
  /** ISO 8601 */
  createdAt: string;
}

export interface ApprovalResponse {
  id: string;
  decision: ApprovalDecision;
  /** ISO 8601 */
  decidedAt: string;
}

export interface ApprovalPolicy {
  action: ApprovalAction;
  requiresApproval: 'always' | 'configurable' | 'never';
  /** Optional list of trusted targets that skip approval */
  allowlist?: string[];
}

export interface AuditEntry {
  id: string;
  taskId: string;
  action: ApprovalAction;
  decision: 'approved' | 'denied' | 'auto_allowed';
  /** ISO 8601 */
  timestamp: string;
  /** Full context snapshot at the time of decision */
  context: Record<string, unknown>;
}
