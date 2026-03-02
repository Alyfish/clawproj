import type { ApprovalAction } from './approvals.js';

// ── Base Card ───────────────────────────────────────────────

export interface CardAction {
  id: string;
  label: string;
  type: 'link' | 'approve' | 'dismiss' | 'copy' | 'custom';
  url?: string;
  approvalAction?: ApprovalAction;
  payload?: Record<string, unknown>;
}

export interface BaseCard {
  id: string;
  /** Open type field — typed cards narrow this to a literal */
  type: string;
  title: string;
  subtitle?: string;
  metadata: Record<string, unknown>;
  actions?: CardAction[];
  ranking?: { label: string; reason: string };
  source?: string;
  /** ISO 8601 */
  createdAt: string;
}

// ── Flight Card ──────────────────────────────────────────────

export interface FlightRoute {
  from: string;
  to: string;
}

export interface Price {
  amount: number;
  currency: string;
}

export interface PointsValue {
  program: string;
  points: number;
}

/** Ranking labels: "Best Overall", "Cheapest", "Fastest", "Best for Points" */
export interface FlightRanking {
  label: string;
  reason: string;
}

export interface FlightCard extends BaseCard {
  type: 'flight';
  airline: string;
  route: FlightRoute;
  /** ISO 8601 */
  departure: string;
  /** ISO 8601 */
  arrival: string;
  /** e.g. "5h 30m" */
  duration: string;
  layovers: number;
  price: Price;
  baggage: string;
  refundPolicy: string;
  visaNotes?: string;
  pointsValue?: PointsValue;
  ranking: FlightRanking;
}

// ── House Card ──────────────────────────────────────────────

export interface Rent {
  amount: number;
  currency: string;
  /** e.g. "month", "week" */
  period: string;
}

export interface Commute {
  destination: string;
  /** e.g. "25 min" */
  time: string;
  /** e.g. "driving", "transit", "walking" */
  mode: string;
}

export interface HouseCard extends BaseCard {
  type: 'house';
  address: string;
  rent: Rent;
  bedrooms: number;
  /** e.g. "750 sqft" */
  area: string;
  commute: Commute;
  leaseTerms: string;
  /** ISO 8601 date */
  moveInDate: string;
  requiredDocs: string[];
  /** Auto-detected issues: unusual deposits, hidden fees, etc. */
  redFlags: string[];
  source: string;
  listingUrl: string;
}

// ── Pick Card (Betting) ─────────────────────────────────────

export interface Matchup {
  home: string;
  away: string;
}

export interface PickCard extends BaseCard {
  type: 'pick';
  matchup: Matchup;
  sport: string;
  league: string;
  line: string;
  impliedOdds: number;
  recentMovement: string;
  notes: string;
  /** e.g. "high", "medium", "low" */
  valueRating: string;
}

// ── Doc Card ────────────────────────────────────────────────

export interface DocCard extends BaseCard {
  type: 'doc';
  /** e.g. "google_doc", "google_sheet", "google_form", "google_slides" */
  docType: string;
  title: string;
  previewText: string;
  url: string;
  mimeType: string;
  /** ISO 8601 — last time the document was modified */
  lastModified?: string;
}

// ── Union ───────────────────────────────────────────────────

export type AnyCard = FlightCard | HouseCard | PickCard | DocCard | BaseCard;
