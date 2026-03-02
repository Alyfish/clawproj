import Foundation

// MARK: - Matchup
// Maps to shared/types/cards.ts → Matchup

struct Matchup: Codable, Equatable {
    let home: String
    let away: String
}

// MARK: - PickCard
// Maps to shared/types/cards.ts → PickCard

struct PickCard: Identifiable, Codable, Equatable {
    let id: String
    let matchup: Matchup
    let sport: String
    let league: String
    let line: String
    let impliedOdds: Double
    let recentMovement: String
    let notes: String
    /// e.g. "high", "medium", "low"
    let valueRating: String

    /// Implied odds as a percentage string, e.g. "62.5%".
    var impliedOddsFormatted: String {
        String(format: "%.1f%%", impliedOdds * 100)
    }

    /// True when recent movement contains "favor" or "↑" (case-insensitive).
    var isMovementFavorable: Bool {
        let lower = recentMovement.lowercased()
        return lower.contains("favor") || recentMovement.contains("↑")
    }
}

// MARK: - Mock Data

extension PickCard {
    static let mockFavorable = PickCard(
        id: "pick-1",
        matchup: Matchup(home: "Lakers", away: "Celtics"),
        sport: "Basketball",
        league: "NBA",
        line: "Lakers -3.5",
        impliedOdds: 0.625,
        recentMovement: "Line moved ↑ from -2.5, sharp money favoring Lakers",
        notes: "Lakers 8-2 in last 10 home games. Celtics missing key starter.",
        valueRating: "high"
    )

    static let mockUnfavorable = PickCard(
        id: "pick-2",
        matchup: Matchup(home: "49ers", away: "Cowboys"),
        sport: "Football",
        league: "NFL",
        line: "49ers -7",
        impliedOdds: 0.48,
        recentMovement: "Line dropped from -8.5, public heavy on Cowboys",
        notes: "Divisional round matchup. Weather could be a factor.",
        valueRating: "low"
    )
}
