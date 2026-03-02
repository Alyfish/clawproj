import { v4 as uuidv4 } from 'uuid';
import type { AuditEntry } from '../../../shared/types/index.js';

// TODO: Replace with persistent store (PostgreSQL, DynamoDB, etc.)

export class AuditLog {
  private entries: AuditEntry[] = [];

  log(entry: Omit<AuditEntry, 'id' | 'timestamp'>): AuditEntry {
    const id = uuidv4();
    const full: AuditEntry = {
      ...entry,
      id,
      timestamp: new Date().toISOString(),
    };
    this.entries.push(full);
    console.log(
      JSON.stringify({
        event: 'audit:logged',
        action: entry.action,
        decision: entry.decision,
        taskId: entry.taskId,
        id,
      }),
    );
    return full;
  }

  getLog(taskId?: string): AuditEntry[] {
    if (taskId) {
      return this.entries.filter((e) => e.taskId === taskId);
    }
    return [...this.entries];
  }

  getEntry(id: string): AuditEntry | undefined {
    return this.entries.find((e) => e.id === id);
  }

  getByAction(action: string): AuditEntry[] {
    return this.entries.filter((e) => e.action === action);
  }

  getByDecision(decision: AuditEntry['decision']): AuditEntry[] {
    return this.entries.filter((e) => e.decision === decision);
  }

  clear(): void {
    this.entries = [];
  }

  size(): number {
    return this.entries.length;
  }

  summary(): {
    total: number;
    approved: number;
    denied: number;
    autoAllowed: number;
  } {
    let approved = 0;
    let denied = 0;
    let autoAllowed = 0;
    for (const e of this.entries) {
      if (e.decision === 'approved') approved++;
      else if (e.decision === 'denied') denied++;
      else if (e.decision === 'auto_allowed') autoAllowed++;
    }
    return { total: this.entries.length, approved, denied, autoAllowed };
  }
}
