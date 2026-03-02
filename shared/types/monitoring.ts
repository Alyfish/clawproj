export interface WatchlistItem {
  id: string;
  taskId: string;
  type: 'price_watch' | 'new_listing' | 'line_movement';
  description: string;
  /** Key-value filters for the monitor (e.g. { airline: "UA", maxPrice: 500 }) */
  filters: Record<string, unknown>;
  /** Check interval in seconds */
  interval: number;
  /** ISO 8601 — last time this item was checked */
  lastChecked?: string;
  active: boolean;
}

export interface MonitoringAlert {
  id: string;
  watchlistItemId: string;
  message: string;
  /** Structured data about what triggered the alert */
  data: Record<string, unknown>;
  /** ISO 8601 */
  timestamp: string;
}
