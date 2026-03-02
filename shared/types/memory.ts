/**
 * ClawBot Memory Type Definitions
 *
 * The memory system gives the agent persistent context across
 * conversations. Memories are key-value entries with markdown
 * content, stored locally and searchable by tag or content.
 *
 * Examples of memories:
 *   key: "user-profile"       → "Name: Alex, lives in SF, works in tech"
 *   key: "flight-preferences" → "Prefers window seat, United MileagePlus member"
 *   key: "past-search-sfo-lhr" → "Searched on Feb 28, best price was $389 on Norse"
 */

// ============================================================
// MEMORY ENTRY — a single stored memory
// ============================================================

/**
 * A single memory entry stored by the agent.
 *
 * Keys are human-readable identifiers that the agent creates
 * and uses to organize knowledge. Tags enable cross-cutting queries.
 *
 * Content is always markdown text — the agent writes it naturally
 * and reads it back as context in future conversations.
 */
export interface MemoryEntry {
  /** Unique identifier (UUID) */
  id: string;
  /**
   * Human-readable key for retrieval.
   * Convention: kebab-case descriptive names.
   * Examples: "user-profile", "flight-preferences",
   *           "past-search-sfo-lhr-2026-02-28"
   */
  key: string;
  /**
   * The memory content as markdown text.
   * Written by the agent, read back as system prompt context.
   */
  content: string;
  /**
   * Tags for categorization and search.
   * Examples: ["user", "preferences"], ["travel", "flights", "search-results"]
   */
  tags: string[];
  /** ISO 8601 creation timestamp */
  createdAt: string;
  /** ISO 8601 last update timestamp */
  updatedAt: string;
  /**
   * What created or last updated this memory.
   * Examples: "conversation-abc123", "skill:travel-search", "user-edit"
   */
  source?: string;
  /**
   * Time-to-live in seconds. If set, the memory expires
   * after this duration from updatedAt.
   * Useful for ephemeral context like "currently searching for X".
   */
  ttl?: number;
}

// ============================================================
// MEMORY SEARCH — query and results
// ============================================================

/**
 * Result of searching the memory store.
 * Includes the matched entry and a relevance score
 * for ranking results.
 */
export interface MemorySearchResult {
  /** The matched memory entry */
  entry: MemoryEntry;
  /**
   * Relevance score (0-1) based on search query match.
   * 1.0 = exact key match, lower values = tag/content match.
   */
  relevanceScore: number;
}

/**
 * Query parameters for searching memories.
 */
export interface MemorySearchQuery {
  /** Text to search in keys, content, and tags */
  query?: string;
  /** Filter by tags (AND — all tags must match) */
  tags?: string[];
  /** Only return memories updated after this ISO 8601 timestamp */
  updatedAfter?: string;
  /** Maximum number of results to return (default: 10) */
  limit?: number;
}

// ============================================================
// MEMORY OPERATIONS — for the memory tool interface
// ============================================================

/**
 * Operations the agent can perform on memories via the memory tool.
 */
export type MemoryOperation =
  | { op: 'get'; key: string }
  | { op: 'set'; key: string; content: string; tags?: string[] }
  | { op: 'delete'; key: string }
  | { op: 'search'; query: MemorySearchQuery }
  | { op: 'list'; tags?: string[]; limit?: number };
