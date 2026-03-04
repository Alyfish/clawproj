import { v4 as uuidv4 } from 'uuid';
import type { AuditEntry } from '../../../shared/types/index.js';
import type { GatewayDB } from '../src/persistence.js';

export class AuditLog {
  private entries: AuditEntry[] = [];

  constructor(private db?: GatewayDB) {
    if (this.db) {
      this.rehydrate();
    }
  }

  private rehydrate(): void {
    if (!this.db) return;
    const rows = this.db.getAuditLog();
    this.entries = rows.map((r) => ({
      id: r.id,
      taskId: r.task_id,
      action: r.action as AuditEntry['action'],
      decision: r.decision as AuditEntry['decision'],
      timestamp: r.timestamp,
      context: JSON.parse(r.context),
    }));
  }

  log(entry: Omit<AuditEntry, 'id' | 'timestamp'>): AuditEntry {
    const id = uuidv4();
    const full: AuditEntry = {
      ...entry,
      id,
      timestamp: new Date().toISOString(),
    };
    this.entries.push(full);

    // Write-through to SQLite
    this.db?.insertAuditEntry(
      id,
      entry.taskId,
      entry.action,
      entry.decision,
      full.timestamp,
      JSON.stringify(entry.context),
    );

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
    this.db?.clearAuditLog();
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
