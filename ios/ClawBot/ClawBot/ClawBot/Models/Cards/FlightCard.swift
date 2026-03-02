import Foundation

// MARK: - FlightRoute
// Maps to shared/types/cards.ts → FlightRoute

struct FlightRoute: Codable, Equatable {
    let from: String
    let to: String
}

// MARK: - Price
// Maps to shared/types/cards.ts → Price

struct Price: Codable, Equatable {
    let amount: Double
    let currency: String

    /// e.g. "$349.00" or "EUR 349.00"
    var formatted: String {
        if currency == "USD" {
            return String(format: "$%.0f", amount)
        }
        return String(format: "%@ %.0f", currency, amount)
    }
}

// MARK: - PointsValue
// Maps to shared/types/cards.ts → PointsValue

struct PointsValue: Codable, Equatable {
    let program: String
    let points: Int

    /// e.g. "45,000 United pts"
    var formatted: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        let pointsStr = formatter.string(from: NSNumber(value: points)) ?? "\(points)"
        return "\(pointsStr) \(program) pts"
    }
}

// MARK: - FlightRanking
// Maps to shared/types/cards.ts → FlightRanking

struct FlightRanking: Codable, Equatable {
    let label: String
    let reason: String
}

// MARK: - FlightCard
// Maps to shared/types/cards.ts → FlightCard

struct FlightCard: Identifiable, Codable, Equatable {
    let id: String
    let airline: String
    let route: FlightRoute
    /// ISO 8601
    let departure: String
    /// ISO 8601
    let arrival: String
    /// e.g. "5h 30m"
    let duration: String
    let layovers: Int
    let price: Price
    let baggage: String
    let refundPolicy: String
    let visaNotes: String?
    let pointsValue: PointsValue?
    let ranking: FlightRanking

    /// Parsed departure date from ISO 8601 string.
    var departureDate: Date? {
        ISO8601DateFormatter().date(from: departure)
    }

    /// Parsed arrival date from ISO 8601 string.
    var arrivalDate: Date? {
        ISO8601DateFormatter().date(from: arrival)
    }

    /// True when the refund policy contains "refundable" (case-insensitive)
    /// and does not contain "non-refundable".
    var isRefundable: Bool {
        let lower = refundPolicy.lowercased()
        return lower.contains("refundable") && !lower.contains("non-refundable")
    }
}

// MARK: - Mock Data

extension FlightCard {
    static let mockDefault = FlightCard(
        id: "flight-1",
        airline: "United Airlines",
        route: FlightRoute(from: "SFO", to: "JFK"),
        departure: "2026-03-15T08:30:00Z",
        arrival: "2026-03-15T17:00:00Z",
        duration: "5h 30m",
        layovers: 0,
        price: Price(amount: 349, currency: "USD"),
        baggage: "1 carry-on, 1 checked",
        refundPolicy: "Refundable within 24 hours",
        visaNotes: nil,
        pointsValue: PointsValue(program: "United", points: 45000),
        ranking: FlightRanking(label: "Best Overall", reason: "Direct flight, good price, includes bags")
    )

    static let mockCheapest = FlightCard(
        id: "flight-2",
        airline: "Spirit Airlines",
        route: FlightRoute(from: "SFO", to: "JFK"),
        departure: "2026-03-15T06:00:00Z",
        arrival: "2026-03-15T18:45:00Z",
        duration: "9h 45m",
        layovers: 1,
        price: Price(amount: 129, currency: "USD"),
        baggage: "1 personal item",
        refundPolicy: "Non-refundable",
        visaNotes: "ESTA required for international connections",
        pointsValue: nil,
        ranking: FlightRanking(label: "Cheapest", reason: "Lowest fare but 1 layover, no bags included")
    )

    static let mockFastest = FlightCard(
        id: "flight-3",
        airline: "JetBlue",
        route: FlightRoute(from: "SFO", to: "JFK"),
        departure: "2026-03-15T07:00:00Z",
        arrival: "2026-03-15T15:15:00Z",
        duration: "5h 15m",
        layovers: 0,
        price: Price(amount: 425, currency: "USD"),
        baggage: "1 carry-on, 1 checked",
        refundPolicy: "Fully refundable",
        visaNotes: nil,
        pointsValue: PointsValue(program: "JetBlue", points: 32000),
        ranking: FlightRanking(label: "Fastest", reason: "Shortest direct flight")
    )
}
