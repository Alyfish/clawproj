import type { AnyCard } from './cards.js';
import type { ApprovalRequest } from './approvals.js';

export type TaskStatus =
  | 'planning'
  | 'searching'
  | 'waiting_input'
  | 'waiting_approval'
  | 'executing'
  | 'monitoring'
  | 'completed'
  | 'stopped';

export interface ThinkingStep {
  id: string;
  description: string;
  status: 'pending' | 'running' | 'done' | 'error';
  toolName?: string;
  result?: string;
  /** ISO 8601 */
  timestamp: string;
}

export interface Task {
  id: string;
  status: TaskStatus;
  /** The user's original request */
  goal: string;
  steps: ThinkingStep[];
  cards: AnyCard[];
  approvals: ApprovalRequest[];
  /** ISO 8601 */
  createdAt: string;
  /** ISO 8601 */
  updatedAt: string;
}

export interface TaskUpdate {
  taskId: string;
  status: TaskStatus;
  step?: ThinkingStep;
  card?: AnyCard;
}
