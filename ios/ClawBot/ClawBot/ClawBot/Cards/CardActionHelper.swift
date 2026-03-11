import SwiftUI

// MARK: - Card Action Types

typealias CardActionHandler = (String) -> Void

// MARK: - AnyCard Payload Extension

extension AnyCard {
    /// Encodes the card as a flat dictionary for the card.action WebSocket payload.
    func toPayload() -> [String: AnyCodable] {
        guard let data = try? JSONEncoder().encode(self),
              let dict = try? JSONDecoder().decode([String: AnyCodable].self, from: data)
        else { return [:] }
        return dict
    }
}

// MARK: - CardActionButton

struct CardActionButton: View {

    let label: String
    let icon: String
    let style: Style
    let isLoading: Bool
    let action: () -> Void

    enum Style {
        case primary    // filled blue
        case secondary  // outlined
        case subtle     // gray text
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                        .tint(foregroundColor)
                } else {
                    Image(systemName: icon)
                }
                Text(label)
            }
            .font(.subheadline)
            .fontWeight(.medium)
            .foregroundStyle(foregroundColor)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 10)
            .background(background)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .overlay(border)
        }
        .disabled(isLoading)
    }

    private var foregroundColor: Color {
        switch style {
        case .primary: .white
        case .secondary: .blue
        case .subtle: .secondary
        }
    }

    @ViewBuilder
    private var background: some View {
        switch style {
        case .primary:
            RoundedRectangle(cornerRadius: 10).fill(.blue)
        case .secondary, .subtle:
            Color.clear
        }
    }

    @ViewBuilder
    private var border: some View {
        switch style {
        case .secondary:
            RoundedRectangle(cornerRadius: 10)
                .strokeBorder(.blue.opacity(0.5), lineWidth: 1)
        case .primary, .subtle:
            EmptyView()
        }
    }
}
