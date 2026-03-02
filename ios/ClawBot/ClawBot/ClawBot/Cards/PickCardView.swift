import SwiftUI

// MARK: - PickCardView

struct PickCardView: View {
    let card: PickCard

    // MARK: - Computed Properties

    private var sportColor: Color {
        switch card.sport.lowercased() {
        case "basketball": return .orange
        case "football": return .brown
        case "baseball": return .red
        case "soccer": return .green
        case "hockey": return .blue
        default: return .gray
        }
    }

    private var valueColor: Color {
        switch card.valueRating.lowercased() {
        case "high", "great value": return .green
        case "medium", "good value", "fair": return .yellow
        case "low", "poor value": return .red
        default: return .gray
        }
    }

    // MARK: - Body

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Matchup + league
            HStack {
                Text("\(card.matchup.away) @ \(card.matchup.home)")
                    .font(.headline)
                Spacer()
                Text(card.league)
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(sportColor, in: Capsule())
            }

            // Line
            Text(card.line)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .frame(maxWidth: .infinity, alignment: .center)

            // Implied odds | value badge | movement
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Implied")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(card.impliedOddsFormatted)
                        .font(.subheadline)
                        .fontWeight(.semibold)
                }

                Spacer()

                RankingBadge(card.valueRating, style: .custom(valueColor))

                Spacer()

                VStack(alignment: .trailing, spacing: 2) {
                    Text("Movement")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    HStack(spacing: 2) {
                        Image(systemName: card.isMovementFavorable ? "arrow.up.right" : "arrow.down.right")
                            .foregroundStyle(card.isMovementFavorable ? .green : .red)
                            .font(.caption)
                        Text(card.isMovementFavorable ? "Favorable" : "Unfavorable")
                            .font(.caption)
                            .foregroundStyle(card.isMovementFavorable ? .green : .red)
                    }
                }
            }

            // Recent movement detail
            Text(card.recentMovement)
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(10)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 8))

            // Notes
            if !card.notes.isEmpty {
                Text(card.notes)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .italic()
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.08), radius: 8, x: 0, y: 2)
    }
}

// MARK: - Previews

#Preview("Good value") {
    PickCardView(card: .mockFavorable)
        .padding()
        .background(Color(.systemGroupedBackground))
}

#Preview("Poor value") {
    PickCardView(card: .mockUnfavorable)
        .padding()
        .background(Color(.systemGroupedBackground))
}

#Preview("Side by side") {
    ScrollView {
        VStack(spacing: 16) {
            PickCardView(card: .mockFavorable)
            PickCardView(card: .mockUnfavorable)
        }
        .padding()
    }
    .background(Color(.systemGroupedBackground))
}
