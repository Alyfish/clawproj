import SwiftUI

struct FlightCardView: View {
    let card: FlightCard
    var onAction: CardActionHandler? = nil
    @State private var loadingAction: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // MARK: - Top: Airline + Ranking Badge
            HStack {
                Text(card.airline)
                    .font(.headline)
                Spacer()
                RankingBadge(card.ranking.label)
            }

            // MARK: - Middle: Route + Times
            HStack(spacing: 16) {
                // Departure
                VStack(alignment: .leading, spacing: 2) {
                    Text(formattedTime(card.departure))
                        .font(.title3)
                        .fontWeight(.semibold)
                    Text(card.route.from)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                // Duration + layover line
                VStack(spacing: 2) {
                    Text(card.duration)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Rectangle()
                        .frame(height: 1)
                        .foregroundStyle(.tertiary)
                    Text(card.layovers == 0 ? "Direct" : "\(card.layovers) stop\(card.layovers > 1 ? "s" : "")")
                        .font(.caption2)
                        .foregroundStyle(card.layovers == 0 ? .green : .orange)
                }
                .frame(maxWidth: .infinity)

                // Arrival
                VStack(alignment: .trailing, spacing: 2) {
                    Text(formattedTime(card.arrival))
                        .font(.title3)
                        .fontWeight(.semibold)
                    Text(card.route.to)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            // MARK: - Visa Notes Banner (if present)
            if let visaNotes = card.visaNotes {
                HStack(spacing: 6) {
                    Image(systemName: "info.circle.fill")
                        .font(.caption)
                        .foregroundStyle(.blue)
                    Text(visaNotes)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.blue.opacity(0.08))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            // MARK: - Bottom: Price + Baggage + Refund
            HStack {
                // Price
                VStack(alignment: .leading, spacing: 2) {
                    Text(card.price.formatted)
                        .font(.title2)
                        .fontWeight(.bold)
                    if let pts = card.pointsValue {
                        Text("or \(pts.formatted)")
                            .font(.caption)
                            .foregroundStyle(.purple)
                    }
                }

                Spacer()

                // Baggage
                VStack(alignment: .center, spacing: 2) {
                    Image(systemName: "suitcase.fill")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(card.baggage)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                // Refund indicator
                VStack(alignment: .trailing, spacing: 2) {
                    Image(systemName: card.isRefundable ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundStyle(card.isRefundable ? .green : .red)
                    Text(card.isRefundable ? "Refundable" : "Non-refundable")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            // Ranking reason
            Text(card.ranking.reason)
                .font(.caption)
                .foregroundStyle(.tertiary)
                .italic()

            // MARK: - Actions
            if onAction != nil {
                HStack(spacing: 8) {
                    CardActionButton(label: "Book This", icon: "airplane", style: .primary,
                                     isLoading: loadingAction == "book") {
                        fireAction("book")
                    }
                    CardActionButton(label: "Watch Price", icon: "bell", style: .secondary,
                                     isLoading: loadingAction == "watch_price") {
                        fireAction("watch_price")
                    }
                }

                ShareLink(item: "\(card.airline) \(card.route.from) → \(card.route.to) \(card.price.formatted)") {
                    HStack(spacing: 6) {
                        Image(systemName: "square.and.arrow.up")
                        Text("Share")
                    }
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                }
            }
        }
        .padding()
        .background(Color(.systemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.08), radius: 8, x: 0, y: 2)
    }

    private func fireAction(_ action: String) {
        loadingAction = action
        onAction?(action)
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            loadingAction = nil
        }
    }

    private func formattedTime(_ iso: String) -> String {
        let formatter = ISO8601DateFormatter()
        guard let date = formatter.date(from: iso) else { return iso }
        let timeFormatter = DateFormatter()
        timeFormatter.dateFormat = "h:mm a"
        return timeFormatter.string(from: date)
    }
}

// MARK: - Previews

#Preview("Best Overall") {
    FlightCardView(card: .mockDefault)
        .padding()
}

#Preview("Cheapest — no points, non-refundable") {
    FlightCardView(card: .mockCheapest)
        .padding()
}

#Preview("Fastest — with points") {
    FlightCardView(card: .mockFastest)
        .padding()
}

#Preview("Card list") {
    ScrollView {
        VStack(spacing: 16) {
            FlightCardView(card: .mockDefault)
            FlightCardView(card: .mockCheapest)
            FlightCardView(card: .mockFastest)
        }
        .padding()
    }
}
