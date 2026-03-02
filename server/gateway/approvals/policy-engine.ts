import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { ApprovalPolicy } from '../../../shared/types/index.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = resolve(__dirname, 'approvals.config.json');

export interface PolicyCheckContext {
  target?: string;
  [key: string]: unknown;
}

export interface PolicyCheckResult {
  requiresApproval: boolean;
  reason: string;
}

interface ConfigEntry {
  action: string;
  requiresApproval: 'always' | 'configurable' | 'never';
  allowlist?: string[];
}

/** Safety-critical actions that always require approval — cannot be overridden by config. */
const ALWAYS_ASK: ReadonlySet<string> = new Set([
  'submit',
  'pay',
  'send',
  'delete',
  'share_personal_info',
]);

const HARDCODED_DEFAULTS: ConfigEntry[] = [
  { action: 'submit', requiresApproval: 'always' },
  { action: 'pay', requiresApproval: 'always' },
  { action: 'send', requiresApproval: 'always' },
  { action: 'delete', requiresApproval: 'always' },
  { action: 'share_personal_info', requiresApproval: 'always' },
];

export class PolicyEngine {
  private policies: Map<string, ConfigEntry> = new Map();

  constructor() {
    this.loadPolicies();
  }

  private loadPolicies(): void {
    try {
      const raw = readFileSync(CONFIG_PATH, 'utf-8');
      const parsed = JSON.parse(raw) as { policies: ConfigEntry[] };
      this.policies = new Map(parsed.policies.map((p) => [p.action, p]));
    } catch {
      this.policies = new Map(HARDCODED_DEFAULTS.map((p) => [p.action, p]));
    }
  }

  checkPolicy(
    action: string,
    context: PolicyCheckContext = {},
  ): PolicyCheckResult {
    // Step 1: ALWAYS_ASK override — hardcoded safety floor
    if (ALWAYS_ASK.has(action)) {
      return {
        requiresApproval: true,
        reason: `"${action}" is a safety-critical action`,
      };
    }

    // Step 2: Unknown action — safe-by-default
    const policy = this.policies.get(action);
    if (!policy) {
      return {
        requiresApproval: true,
        reason: `unknown action "${action}" defaults to requiring approval`,
      };
    }

    // Step 3: never
    if (policy.requiresApproval === 'never') {
      return {
        requiresApproval: false,
        reason: `"${action}" is configured as never requiring approval`,
      };
    }

    // Step 4: always
    if (policy.requiresApproval === 'always') {
      return {
        requiresApproval: true,
        reason: `"${action}" is configured as always requiring approval`,
      };
    }

    // Step 5: configurable — check allowlist
    if (policy.requiresApproval === 'configurable') {
      const target = context.target;
      if (target && policy.allowlist?.includes(target)) {
        return {
          requiresApproval: false,
          reason: `"${action}" target "${target}" is in the allowlist`,
        };
      }
      return {
        requiresApproval: true,
        reason: `"${action}" requires approval — target not in allowlist`,
      };
    }

    // Fallback (should never reach here)
    return {
      requiresApproval: true,
      reason: `unhandled policy type for "${action}"`,
    };
  }

  reloadPolicies(): void {
    this.loadPolicies();
  }

  getPolicy(action: string): ConfigEntry | undefined {
    return this.policies.get(action);
  }

  listPolicies(): ConfigEntry[] {
    return [...this.policies.values()];
  }
}
