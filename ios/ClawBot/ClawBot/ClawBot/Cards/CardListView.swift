import SwiftUI

// MARK: - CardListView (ScrollView variant)

struct CardListView: View {
    let cards: [AnyCard]
    var onSave: ((AnyCard) -> Void)?
    var onDismiss: ((AnyCard) -> Void)?

    var body: some View {
        ScrollView {
            if cards.isEmpty {
                emptyState
            } else {
                LazyVStack(spacing: 16) {
                    ForEach(cards) { card in
                        cardView(for: card)
                    }
                }
                .padding()
            }
        }
    }

    @ViewBuilder
    private func cardView(for card: AnyCard) -> some View {
        switch card {
        case .flight(let flight):
            FlightCardView(card: flight)
        case .house(let house):
            HouseCardView(card: house)
        case .pick(let pick):
            PickCardView(card: pick)
        case .doc(let doc):
            DocCardView(card: doc)
        case .base(let base):
            GenericCardView(card: base)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "rectangle.on.rectangle.slash")
                .font(.system(size: 48))
                .foregroundStyle(.tertiary)
            Text("No Cards Yet")
                .font(.headline)
                .foregroundStyle(.secondary)
            Text("Results will appear here as ClawBot finds options for you.")
                .font(.subheadline)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - CardListWithSwipeView (List variant)

struct CardListWithSwipeView: View {
    let cards: [AnyCard]
    var onSave: ((AnyCard) -> Void)?
    var onDismiss: ((AnyCard) -> Void)?

    var body: some View {
        List {
            ForEach(cards) { card in
                cardView(for: card)
                    .listRowSeparator(.hidden)
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                    .swipeActions(edge: .leading) {
                        if let onSave {
                            Button {
                                onSave(card)
                            } label: {
                                Label("Save", systemImage: "bookmark")
                            }
                            .tint(.blue)
                        }
                    }
                    .swipeActions(edge: .trailing) {
                        if let onDismiss {
                            Button(role: .destructive) {
                                onDismiss(card)
                            } label: {
                                Label("Dismiss", systemImage: "xmark")
                            }
                        }
                    }
            }
        }
        .listStyle(.plain)
    }

    @ViewBuilder
    private func cardView(for card: AnyCard) -> some View {
        switch card {
        case .flight(let flight):
            FlightCardView(card: flight)
        case .house(let house):
            HouseCardView(card: house)
        case .pick(let pick):
            PickCardView(card: pick)
        case .doc(let doc):
            DocCardView(card: doc)
        case .base(let base):
            GenericCardView(card: base)
        }
    }
}

// MARK: - Previews

#Preview("Mixed card list") {
    CardListView(cards: AnyCard.mockCards)
}

#Preview("Empty state") {
    CardListView(cards: [])
}

#Preview("List with swipe actions") {
    CardListWithSwipeView(
        cards: AnyCard.mockCards,
        onSave: { card in print("Saved \(card.id)") },
        onDismiss: { card in print("Dismissed \(card.id)") }
    )
}
