/**
 * ClawBot Skill Type Definitions
 *
 * Skills are markdown files (SKILL.md) that define a capability
 * the agent can use. They're loaded at startup by the Skill Loader
 * and injected into the system prompt so the agent knows what it can do.
 *
 * Skills can reference base tools (web_search, file_io, etc.)
 * and declare which approval actions they might trigger.
 */

// ============================================================
// SKILL MANIFEST — full metadata from SKILL.md frontmatter
// ============================================================

/**
 * Complete skill metadata parsed from a SKILL.md file's
 * YAML frontmatter. Used by the skill loader and skill creator.
 *
 * Example SKILL.md frontmatter:
 * ---
 * name: travel-search
 * description: Search for flights, hotels, and transportation
 * tools:
 *   - web_search
 *   - browser
 * approvalActions:
 *   - pay
 * version: 1.0.0
 * author: clawbot
 * ---
 */
export interface SkillManifest {
  /** Unique skill identifier (kebab-case, e.g., "travel-search") */
  name: string;
  /** Human-readable description of what this skill does */
  description: string;
  /**
   * Base tool names this skill uses. The agentic loop ensures
   * these tools are available when the skill is active.
   * Examples: ["web_search", "browser", "file_io"]
   */
  tools?: string[];
  /**
   * Approval actions this skill might trigger.
   * Mapped to the approval policy engine.
   * Examples: ["pay", "send", "delete"]
   */
  approvalActions?: string[];
  /** Semantic version string */
  version?: string;
  /** Author name or identifier */
  author?: string;
  /**
   * Tags for categorization and discovery.
   * Examples: ["travel", "search", "booking"]
   */
  tags?: string[];
  /**
   * Other skill names this skill depends on.
   * The skill loader ensures dependencies are loaded first.
   */
  dependencies?: string[];
  /**
   * Whether this skill is enabled by default.
   * Default: true
   */
  enabled?: boolean;
}

// ============================================================
// SKILL SUMMARY — lightweight reference for system prompt
// ============================================================

/**
 * Compact skill reference injected into the agent's system prompt.
 * The agent reads these to know what skills are available and
 * what each one does (one-liner description).
 *
 * The agent can then request the full SKILL.md content via
 * the skill loader when it needs detailed instructions.
 */
export interface SkillSummary {
  /** Skill name (matches SkillManifest.name) */
  name: string;
  /** One-line description for the system prompt */
  description: string;
  /** Filesystem path to the SKILL.md file */
  path: string;
}

// ============================================================
// SKILL CONTEXT — runtime state during execution
// ============================================================

/**
 * Runtime context passed to a skill when the agent activates it.
 * Contains references the skill's instructions may need.
 */
export interface SkillContext {
  /** The skill being executed */
  skill: SkillSummary;
  /** Full SKILL.md content (loaded on demand) */
  instructions: string;
  /** Available tool names for this skill */
  availableTools: string[];
}

// ============================================================
// SKILL LOADER RESULT — what the loader returns at startup
// ============================================================

/**
 * Result of loading all skills from the filesystem.
 */
export interface SkillLoaderResult {
  /** Successfully loaded skill summaries */
  skills: SkillSummary[];
  /** Full manifests keyed by skill name */
  manifests: Record<string, SkillManifest>;
  /** Skills that failed to load (name → error message) */
  errors: Record<string, string>;
}
