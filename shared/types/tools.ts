/**
 * ClawBot Tool Type Definitions
 *
 * Tools are the atomic operations the agent can perform.
 * Each tool has a name, description, and typed parameters.
 * Skills compose multiple tools to accomplish higher-level tasks.
 *
 * The agentic loop sends ToolCall messages and receives ToolResult responses.
 */

// ============================================================
// TOOL DEFINITION — describes a tool's interface
// ============================================================

/**
 * Describes a single parameter accepted by a tool.
 */
export interface ParameterDef {
  type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  description: string;
  required: boolean;
  default?: unknown;
  /** For 'array' type, the type of each element */
  items?: ParameterDef;
  /** For 'object' type, nested properties */
  properties?: Record<string, ParameterDef>;
  /** For 'string' type, restrict to specific values */
  enum?: string[];
}

/**
 * Defines a tool that the agent can invoke.
 *
 * Tools are registered with the agentic loop at startup.
 * The agent sees the name + description + parameters to decide
 * when to call the tool and with what arguments.
 *
 * Examples:
 *   { name: 'web_search', description: 'Search the web', parameters: { query: { type: 'string', ... } } }
 *   { name: 'file_read', description: 'Read a file', parameters: { path: { type: 'string', ... } } }
 */
export interface ToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, ParameterDef>;
  /**
   * If this tool can trigger actions that need user approval,
   * list those actions here. The agentic loop will check
   * the approval policy before executing.
   * Examples: ['pay', 'send', 'delete']
   */
  requiresApproval?: string[];
}

// ============================================================
// TOOL CALL — agent requests a tool invocation
// ============================================================

/**
 * A request from the agent to invoke a specific tool.
 * Created by Claude during the agentic loop when it decides
 * to use a tool. The loop executor resolves the tool and
 * runs it with the provided input.
 */
export interface ToolCall {
  /** Unique ID for this call (used to correlate with ToolResult) */
  id: string;
  /** Tool name (must match a registered ToolDefinition.name) */
  name: string;
  /** Arguments passed to the tool, keyed by parameter name */
  input: Record<string, unknown>;
}

// ============================================================
// TOOL RESULT — tool execution outcome
// ============================================================

/**
 * The result of executing a tool call.
 * Returned to the agent so it can process the output
 * and decide on next steps.
 */
export interface ToolResult {
  /** Matches the ToolCall.id that produced this result */
  toolCallId: string;
  /** Whether the tool executed successfully */
  success: boolean;
  /**
   * The tool's output. Shape depends on the tool:
   * - web_search: { results: SearchResult[] }
   * - file_read: { content: string }
   * - vision: { description: string, extractedData: unknown }
   */
  output: unknown;
  /** Error message if success is false */
  error?: string;
  /** Execution time in milliseconds */
  durationMs?: number;
}

// ============================================================
// TOOL REGISTRY — for runtime tool management
// ============================================================

/**
 * A tool implementation that can be registered with the agentic loop.
 * Combines the static definition with the executable function signature.
 */
export interface ToolRegistryEntry {
  definition: ToolDefinition;
  /**
   * Whether this tool is currently enabled.
   * Disabled tools are not offered to the agent.
   */
  enabled: boolean;
  /** Which skill provides this tool (if any) */
  providedBy?: string;
}
