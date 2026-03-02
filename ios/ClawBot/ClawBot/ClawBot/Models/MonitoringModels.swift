import Foundation

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
    /// Check interval in seconds
    let interval: Int
    /// ISO 8601
    let lastChecked: String?
    var active: Bool

    // MARK: - Computed

    var intervalFormatted: String {
        if interval < 60 {
            return "\(interval)s"
        } else if interval < 3600 {
            return "\(interval / 60)m"
        } else {
            return "\(interval / 3600)h"
        }
    }

    var lastCheckedFormatted: String? {
        guard let lastChecked else { return nil }
        guard let date = ISO8601DateFormatter().date(from: lastChecked) else { return lastChecked }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

// MARK: - MonitoringAlert
// Maps to shared/types/monitoring.ts → MonitoringAlert

struct MonitoringAlert: Identifiable, Codable, Equatable {
    let id: String
    let watchlistItemId: String
    let message: String
    let data: [String: String]
    /// ISO 8601
    let timestamp: String

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
        interval: 3600,
        lastChecked: "2026-02-28T09:00:00Z",
        active: true
    )

    static let mockNewListing = WatchlistItem(
        id: "watch-002",
        taskId: "task-002",
        type: .newListing,
        description: "2BR in Williamsburg under $3,500",
        filters: ["area": "Williamsburg", "bedrooms": "2", "maxRent": "3500"],
        interval: 1800,
        lastChecked: "2026-02-28T10:30:00Z",
        active: true
    )

    static let mockLineMovement = WatchlistItem(
        id: "watch-003",
        taskId: "task-004",
        type: .lineMovement,
        description: "Lakers -3.5 spread movement",
        filters: ["team": "Lakers", "spread": "-3.5"],
        interval: 300,
        lastChecked: nil,
        active: false
    )
}

extension MonitoringAlert {
    static let mockPriceDrop = MonitoringAlert(
        id: "alert-001",
        watchlistItemId: "watch-001",
        message: "Price dropped to $349 on United UA 456",
        data: ["airline": "United", "flight": "UA 456", "price": "349"],
        timestamp: "2026-02-28T11:00:00Z"
    )

    static let mockNewApt = MonitoringAlert(
        id: "alert-002",
        watchlistItemId: "watch-002",
        message: "New listing: 2BR at 145 Bedford Ave for $3,200/mo",
        data: ["address": "145 Bedford Ave", "rent": "3200", "bedrooms": "2"],
        timestamp: "2026-02-28T12:15:00Z"
    )

    static let mockLineAlert = MonitoringAlert(
        id: "alert-003",
        watchlistItemId: "watch-003",
        message: "Lakers spread moved from -3.5 to -4.0",
        data: ["team": "Lakers", "oldSpread": "-3.5", "newSpread": "-4.0"],
        timestamp: "2026-02-28T13:30:00Z"
    )
}
