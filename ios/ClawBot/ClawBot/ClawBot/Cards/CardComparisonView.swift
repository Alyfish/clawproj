import SwiftUI

// MARK: - CardComparisonView

struct CardComparisonView: View {
    let cards: [AnyCard]
    var onCardAction: ((String, AnyCard) -> Void)?
    @State private var currentPage = 0

    var body: some View {
        VStack(spacing: 12) {
            // Header
            HStack {
                Text("Compare (\(cards.count))")
                    .font(.headline)
                Spacer()
                Text("\(currentPage + 1) of \(cards.count)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal)

            // Paged cards
            TabView(selection: $currentPage) {
                ForEach(Array(cards.enumerated()), id: \.element.id) { index, card in
                    cardView(for: card)
                        .padding(.horizontal)
                        .tag(index)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .automatic))
            .frame(height: cardHeight)

            // Comparison bars
            if let flightBar = flightComparisonBar {
                flightBar
                    .padding(.horizontal)
            }

            if let houseBar = houseComparisonBar {
                houseBar
                    .padding(.horizontal)
            }
        }
    }

    // MARK: - Card Dispatch

    @ViewBuilder
    private func cardView(for card: AnyCard) -> some View {
        switch card {
        case .flight(let flight):
            FlightCardView(card: flight, onAction: handler(for: card))
        case .house(let house):
            HouseCardView(card: house, onAction: handler(for: card))
        case .pick(let pick):
            PickCardView(card: pick, onAction: handler(for: card))
        case .doc(let doc):
            DocCardView(card: doc)
        case .base(let base):
            GenericCardView(card: base, onAction: handler(for: card))
        }
    }

    private func handler(for card: AnyCard) -> CardActionHandler? {
        guard let onCardAction else { return nil }
        return { action in onCardAction(action, card) }
    }

    // MARK: - Card Height

    private var cardHeight: CGFloat {
        guard let first = cards.first else { return 250 }
        switch first {
        case .flight: return 420
        case .house: return 580
        case .pick: return 380
        case .doc: return 250
        case .base: return 450
        }
    }

    // MARK: - Flight Comparison Bar

    @ViewBuilder
    private var flightComparisonBar: (some View)? {
        let flights = cards.compactMap { card -> FlightCard? in
            if case .flight(let f) = card { return f }
            return nil
        }
        if flights.count == cards.count, flights.count > 1 {
            let cheapest = flights.min(by: { $0.price.amount < $1.price.amount })
            let fastest = flights.min(by: { $0.duration < $1.duration })
            HStack(spacing: 12) {
                if let cheapest {
                    ComparisonChip(
                        icon: "dollarsign.circle",
                        label: "Cheapest",
                        value: "\(cheapest.airline) — \(cheapest.price.formatted)",
                        highlight: .green
                    )
                }
                if let fastest {
                    ComparisonChip(
                        icon: "bolt.fill",
                        label: "Fastest",
                        value: "\(fastest.airline) — \(fastest.duration)",
                        highlight: .orange
                    )
                }
            }
        }
    }

    // MARK: - House Comparison Bar

    @ViewBuilder
    private var houseComparisonBar: (some View)? {
        let houses = cards.compactMap { card -> HouseCard? in
            if case .house(let h) = card { return h }
            return nil
        }
        if houses.count == cards.count, houses.count > 1 {
            let cheapest = houses.min(by: { $0.rent.amount < $1.rent.amount })
            let fewestFlags = houses.min(by: { $0.redFlags.count < $1.redFlags.count })
            HStack(spacing: 12) {
                if let cheapest {
                    ComparisonChip(
                        icon: "dollarsign.circle",
                        label: "Cheapest",
                        value: "\(cheapest.rent.formatted) — \(cheapest.bedroomLabel)",
                        highlight: .green
                    )
                }
                if let fewestFlags {
                    ComparisonChip(
                        icon: "exclamationmark.shield",
                        label: "Fewest Flags",
                        value: "\(fewestFlags.redFlags.count) issue\(fewestFlags.redFlags.count == 1 ? "" : "s")",
                        highlight: fewestFlags.redFlags.isEmpty ? .green : .orange
                    )
                }
            }
        }
    }
}

// MARK: - ComparisonChip

private struct ComparisonChip: View {
    let icon: String
    let label: String
    let value: String
    let highlight: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.subheadline)
                .foregroundStyle(highlight)
            VStack(alignment: .leading, spacing: 1) {
                Text(label)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.caption)
                    .fontWeight(.medium)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(highlight.opacity(0.1))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

// MARK: - Previews

#Preview("Compare flights") {
    CardComparisonView(cards: [
        .flight(.mockDefault),
        .flight(.mockCheapest),
        .flight(.mockFastest),
    ])
    .padding()
}

#Preview("Compare houses") {
    CardComparisonView(cards: [
        .house(.mockClean),
        .house(.mockRedFlags),
    ])
    .padding()
}

#Preview("Mixed cards") {
    CardComparisonView(cards: AnyCard.mockCards)
        .padding()
}
