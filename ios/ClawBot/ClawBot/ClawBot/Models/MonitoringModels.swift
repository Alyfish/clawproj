import Foundation
import SwiftUI

// MARK: - WatchlistType
// Maps to shared/types/monitoring.ts → WatchlistItem.type

enum WatchlistType: String, Codable, CaseIterable {
    case priceWatch = "price_watch"
    case newListing = "new_listing"
    case lineMovement = "line_movement"

    var displayName: String {
        switch self {
        case .priceWatch:    return "Price Watch"
        case .newListing:    return "New Listing"
        case .lineMovement:  return "Line Movement"
        }
    }

    var iconName: String {
        switch self {
        case .priceWatch:    return "tag"
        case .newListing:    return "house"
        case .lineMovement:  return "chart.line.uptrend.xyaxis"
        }
    }
}

// MARK: - WatchlistItem
// Maps to shared/types/monitoring.ts → WatchlistItem

struct WatchlistItem: Identifiable, Codable, Equatable, Hashable {
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
    static func == (lhs: WatchlistItem, rhs: WatchlistItem) -> Bool { lhs.id == rhs.id && lhs.active == rhs.active }

    let id: String
    let taskId: String
    let type: WatchlistType
    let description: String
    let filters: [String: String]
    /// Schedule interval (preset name like "every_6_hours" or cron expression)
    let interval: String
    /// ISO 8601
    let lastChecked: String?
    var active: Bool

    // MARK: - Computed

    var intervalFormatted: String {
        // Handle scheduler preset names (e.g., "every_6_hours" → "Every 6 hours")
        let cleaned = interval.replacingOccurrences(of: "_", with: " ")
        if cleaned.hasPrefix("every ") || cleaned.hasPrefix("daily ") {
            return cleaned.capitalized
        }
        if cleaned == "weekly" { return "Weekly" }
        // Fallback: show raw value (cron expression)
        return interval
    }

    var lastCheckedFormatted: String? {
        guard let lastChecked else { return nil }
        guard let date = ISO8601DateFormatter().date(from: lastChecked) else { return lastChecked }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

// MARK: - WatchlistAlert
// Enriched alert model — built from gateway schedule/watch:update events.

struct WatchlistAlert: Identifiable, Codable, Equatable {
    let id: String
    let watchId: String
    let alertType: String       // "price_drop", "price_increase", "new_listing", "listing_removed", "line_movement"
    let title: String
    let message: String
    let source: String          // skill name (e.g. "price_monitor")
    let previousValue: String?
    let currentValue: String?
    let url: String?
    let cardType: String?       // "flight", "house", "pick"
    /// ISO 8601
    let timestamp: String
    var isRead: Bool = false

    // MARK: - Computed

    var alertIcon: String {
        switch alertType {
        case "price_drop":       return "arrow.down.circle.fill"
        case "price_increase":   return "arrow.up.circle.fill"
        case "new_listing":      return "plus.circle.fill"
        case "listing_removed":  return "minus.circle.fill"
        case "line_movement":    return "arrow.left.arrow.right.circle.fill"
        default:                 return "bell.circle.fill"
        }
    }

    var alertColor: Color {
        switch alertType {
        case "price_drop":       return .green
        case "price_increase":   return .red
        case "new_listing":      return .blue
        case "listing_removed":  return .orange
        case "line_movement":    return .purple
        default:                 return .gray
        }
    }

    var relativeTime: String {
        guard let date = ISO8601DateFormatter().date(from: timestamp) else { return timestamp }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }

    var date: Date? {
        ISO8601DateFormatter().date(from: timestamp)
    }
}

// MARK: - Mocks

extension WatchlistItem {
    static let mockPriceWatch = WatchlistItem(
        id: "watch-001",
        taskId: "task-001",
        type: .priceWatch,
        description: "SFO → JFK under $400 round-trip",
        filters: ["origin": "SFO", "destination": "JFK", "maxPrice": "400"],
        interval: "every_hour",
        lastChecked: "2026-02-28T09:00:00Z",
        active: true
    )

    static let mockNewListing = WatchlistItem(
        id: "watch-002",
        taskId: "task-002",
        type: .newListing,
        description: "2BR in Williamsburg under $3,500",
        filters: ["area": "Williamsburg", "bedrooms": "2", "maxRent": "3500"],
        interval: "every_hour",
        lastChecked: "2026-02-28T10:30:00Z",
        active: true
    )

    static let mockLineMovement = WatchlistItem(
        id: "watch-003",
        taskId: "task-004",
        type: .lineMovement,
        description: "Lakers -3.5 spread movement",
        filters: ["team": "Lakers", "spread": "-3.5"],
        interval: "every_5_minutes",
        lastChecked: nil,
        active: false
    )
}

extension WatchlistAlert {
    static let mockPriceDrop = WatchlistAlert(
        id: "alert-001",
        watchId: "watch-001",
        alertType: "price_drop",
        title: "SFO → JFK under $400 round-trip",
        message: "Price dropped to $349 on United UA 456",
        source: "price_monitor",
        previousValue: "$389",
        currentValue: "$349",
        url: nil,
        cardType: "flight",
        timestamp: "2026-02-28T11:00:00Z"
    )

    static let mockNewApt = WatchlistAlert(
        id: "alert-002",
        watchId: "watch-002",
        alertType: "new_listing",
        title: "2BR in Williamsburg under $3,500",
        message: "New listing: 2BR at 145 Bedford Ave for $3,200/mo",
        source: "apartment_search",
        previousValue: nil,
        currentValue: "$3,200/mo",
        url: "https://streeteasy.com/listing/12345",
        cardType: "house",
        timestamp: "2026-02-28T12:15:00Z"
    )

    static let mockLineAlert = WatchlistAlert(
        id: "alert-003",
        watchId: "watch-003",
        alertType: "line_movement",
        title: "Lakers -3.5 spread movement",
        message: "Lakers spread moved from -3.5 to -4.0",
        source: "betting_odds",
        previousValue: "-3.5",
        currentValue: "-4.0",
        url: nil,
        cardType: "pick",
        timestamp: "2026-02-28T13:30:00Z"
    )
}
