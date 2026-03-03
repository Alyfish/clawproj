import SwiftUI

/// Chat bubble that renders assistant messages with full markdown and user messages
/// as plain text in a blue rounded rect.
struct MessageBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user {
                Spacer(minLength: 60)
            }

            Group {
                if let card = message.card {
                    cardView(for: card)
                } else if message.role == .assistant {
                    if message.isStreaming && message.content.isEmpty {
                        ProgressView()
                            .controlSize(.small)
                            .padding(12)
                    } else {
                        MarkdownContentView(message.content, foregroundColor: Color(.label))
                            .font(.system(size: 17))
                            .textSelection(.enabled)
                    }
                } else {
                    Text(message.content)
                        .font(.system(size: 17))
                        .foregroundStyle(.white)
                }
            }
            .padding(message.card != nil ? 0 : (message.role == .user ? 12 : 0))
            .background(
                message.role == .user && message.card == nil
                    ? RoundedRectangle(cornerRadius: 18)
                        .fill(Color.blue)
                    : nil
            )
            .contextMenu {
                Button {
                    UIPasteboard.general.string = message.content
                } label: {
                    Label("Copy", systemImage: "doc.on.doc")
                }
            }

            if message.role == .assistant || message.card != nil {
                Spacer(minLength: 0)
            }
        }
    }

    // MARK: - Card dispatch

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

#Preview("User bubble") {
    MessageBubbleView(message: ChatMessage(role: .user, content: "Find me a flight to NYC"))
        .padding()
}

#Preview("Assistant bubble") {
    MessageBubbleView(message: ChatMessage(
        role: .assistant,
        content: "Here are **3 options** for flights:\n\n1. Delta — $320\n2. JetBlue — $289\n3. United — $305\n\n> All prices include taxes."
    ))
    .padding()
}

#Preview("Streaming empty") {
    MessageBubbleView(message: ChatMessage.assistantPlaceholder())
        .padding()
}

#Preview("Card bubble — Flight") {
    MessageBubbleView(message: ChatMessage(
        role: .assistant,
        content: "",
        card: .flight(.mockDefault)
    ))
    .padding()
}

#Preview("Card bubble — Generic") {
    MessageBubbleView(message: ChatMessage(
        role: .assistant,
        content: "",
        card: .base(.mockShopifyOrder)
    ))
    .padding()
}
